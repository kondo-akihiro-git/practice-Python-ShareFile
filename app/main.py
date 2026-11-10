from __future__ import annotations

import ipaddress
import json
import os
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect, Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import ROOT, Settings, load_settings
from .storage import Storage, StorageError

STATIC_DIR = ROOT / "app" / "static"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "ShareFile"
MAX_JSON_BYTES = 1024 * 1024
CHUNK = 1024 * 1024
APP_CSP = ("default-src 'self'; img-src 'self' blob: data:; media-src 'self'; "
           "style-src 'self' 'unsafe-inline'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")


def _host_allowed(host: str, extra: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".ts.net") or host in extra:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip in ipaddress.ip_network("100.64.0.0/10") or ip in ipaddress.ip_network("fd7a:115c:a1e0::/48")


def _hostname(netloc: str) -> str:
    return (urlsplit("//" + netloc).hostname or "").lower()


class GuardMiddleware:
    """Hostヘッダ検証(DNSリバインディング対策)、CSRF対策、セキュリティヘッダ付与。"""

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.extra = settings.allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = _hostname(headers.get("host", ""))
        error = None
        if not host or not _host_allowed(host, self.extra):
            error = (421, "このホスト名ではアクセスできません")
        elif scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            origin = headers.get("origin")
            if headers.get(CSRF_HEADER) != CSRF_VALUE:
                error = (403, "不正なリクエストです")
            elif origin and _hostname(origin.split("://", 1)[-1]) != host:
                error = (403, "別のオリジンからの操作は許可されていません")
            elif headers.get("sec-fetch-site") == "cross-site":
                error = (403, "別のサイトからの操作は許可されていません")
        if error:
            resp: Response = JSONResponse({"error": error[1]}, status_code=error[0])
            await resp(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                hdrs = message.setdefault("headers", [])
                present = {k.lower() for k, _ in hdrs}
                path = scope["path"]
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"content-security-policy",
                     b"frame-ancestors 'self'" if path == "/api/file" else APP_CSP.encode()),
                ]
                if path.startswith("/api/") and path != "/api/file":
                    extra.append((b"cache-control", b"no-store"))
                for k, v in extra:
                    if k not in present:
                        hdrs.append((k, v))
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app(settings: Settings | None = None) -> Starlette:
    settings = settings or load_settings()
    storage = Storage(settings.shared_dir, settings.trash_dir)
    storage.cleanup_partials()

    def err(status: int, message: str) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status)

    async def read_json(request: Request) -> dict:
        size = 0
        buf = bytearray()
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_JSON_BYTES:
                raise StorageError(413, "リクエストが大きすぎます")
            buf += chunk
        try:
            data = json.loads(buf or b"{}")
        except (ValueError, UnicodeDecodeError):
            raise StorageError(400, "JSONが不正です") from None
        if not isinstance(data, dict):
            raise StorageError(400, "JSONが不正です")
        return data

    def qp(request: Request, key: str, default: str = "") -> str:
        return request.query_params.get(key, default)

    def qint(request: Request, key: str, default: int) -> int:
        try:
            return int(qp(request, key, str(default)))
        except ValueError:
            raise StorageError(400, f"{key}が不正です") from None

    async def index(request: Request):
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    async def config(request: Request):
        return JSONResponse({"name": "シェアファイル", "max_upload_bytes": settings.max_upload_bytes})

    async def list_(request: Request):
        sort = qp(request, "sort", "name")
        order = qp(request, "order", "asc")
        if sort not in ("name", "mtime", "size") or order not in ("asc", "desc"):
            raise StorageError(400, "並び替え指定が不正です")
        data = await run_in_threadpool(
            storage.list, qp(request, "path"), sort, order, qp(request, "q"),
            qp(request, "recursive") == "1", qint(request, "offset", 0), qint(request, "limit", 200))
        return JSONResponse(data)

    async def dirs(request: Request):
        return JSONResponse({"dirs": await run_in_threadpool(storage.all_dirs)})

    async def info(request: Request):
        data = await run_in_threadpool(storage.info, qp(request, "path"), qp(request, "hash") == "1")
        return JSONResponse(data)

    async def file(request: Request):
        full = storage.resolve_file(qp(request, "path"))
        name = full.name
        from .storage import kind_of, mime_of
        kind = kind_of(name, False)
        download = qp(request, "download") == "1"
        mime = mime_of(name)
        if download or kind not in ("image", "pdf", "video", "text"):
            return FileResponse(full, media_type="application/octet-stream" if kind == "file" and download
                                else mime, filename=name, content_disposition_type="attachment")
        headers = {}
        if kind == "text":
            mime = "text/plain; charset=utf-8"
        if kind != "pdf":
            headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return FileResponse(full, media_type=mime, filename=name, content_disposition_type="inline",
                            headers=headers)

    async def upload(request: Request):
        name = qp(request, "name")
        mode = qp(request, "mode", "fail")
        raw_len = request.headers.get("content-length")
        if raw_len is None:
            raise StorageError(411, "Content-Lengthが必要です")
        try:
            expected = int(raw_len)
            if expected < 0:
                raise ValueError
        except ValueError:
            raise StorageError(400, "Content-Lengthが不正です") from None
        try:
            mtime_ms = int(request.headers.get("x-last-modified", "0") or 0)
        except ValueError:
            mtime_ms = 0
        directory, part = storage.begin_upload(qp(request, "dir"), name, mode, expected,
                                               settings.max_upload_bytes)
        import hashlib
        h = hashlib.sha256()
        total = 0
        f = await run_in_threadpool(open, part, "xb")
        ok = False
        try:
            async for chunk in request.stream():
                total += len(chunk)
                if total > settings.max_upload_bytes or total > expected:
                    raise StorageError(413, "ファイルが大きすぎます")
                h.update(chunk)
                await run_in_threadpool(f.write, chunk)
            if total != expected:
                raise StorageError(400, "データが途中で途切れました")
            await run_in_threadpool(f.close)
            rel = await run_in_threadpool(storage.finish_upload, directory, part, name, mode, mtime_ms)
            ok = True
        finally:
            if not f.closed:
                f.close()
            if not ok:
                try:
                    os.unlink(part)
                except OSError:
                    pass
        return JSONResponse({"path": rel, "name": os.path.basename(rel), "size": total,
                             "sha256": h.hexdigest()}, status_code=201)

    async def mkdir(request: Request):
        d = await read_json(request)
        return JSONResponse({"path": storage.mkdir(str(d.get("path", "")), d.get("name"))}, status_code=201)

    async def rename(request: Request):
        d = await read_json(request)
        return JSONResponse({"path": storage.rename(str(d.get("path", "")), d.get("name"))})

    async def move(request: Request):
        d = await read_json(request)
        paths = d.get("paths")
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise StorageError(400, "pathsが不正です")
        return JSONResponse({"paths": storage.move(paths, str(d.get("dest", "")))})

    async def delete(request: Request):
        d = await read_json(request)
        if d.get("confirm") is not True:
            raise StorageError(400, "削除には確認(confirm)が必要です")
        storage.delete(str(d.get("path", "")))
        return JSONResponse({"ok": True})

    async def storage_error(request: Request, exc: StorageError):
        return err(exc.status, exc.message)

    async def http_error(request: Request, exc: HTTPException):
        return err(exc.status_code, exc.detail if isinstance(exc.detail, str) else "エラー")

    async def unexpected(request: Request, exc: Exception):
        if isinstance(exc, ClientDisconnect):
            return Response(status_code=499)
        return err(500, "サーバー内部エラーが発生しました")

    routes = [
        Route("/", index, methods=["GET"]),
        Route("/api/config", config, methods=["GET"]),
        Route("/api/list", list_, methods=["GET"]),
        Route("/api/dirs", dirs, methods=["GET"]),
        Route("/api/info", info, methods=["GET"]),
        Route("/api/file", file, methods=["GET"]),
        Route("/api/upload", upload, methods=["PUT"]),
        Route("/api/mkdir", mkdir, methods=["POST"]),
        Route("/api/rename", rename, methods=["POST"]),
        Route("/api/move", move, methods=["POST"]),
        Route("/api/delete", delete, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ]
    app = Starlette(
        routes=routes,
        exception_handlers={StorageError: storage_error, HTTPException: http_error, Exception: unexpected},
    )
    app.state.storage = storage
    app.state.settings = settings
    return GuardMiddleware(app, settings)
