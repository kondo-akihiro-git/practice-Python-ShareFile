"""共有フォルダ上のファイル操作。共有フォルダ外へのアクセスはここで全て拒否する。"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

INTERNAL_PREFIX = ".sharefile-"
PART_SUFFIX = ".part"
HIDDEN_NAMES = {".gitkeep"}
MAX_NAME_BYTES = 255
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/heif", ".heif")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/quicktime", ".mov")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".avif", ".bmp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
TEXT_EXT = {".txt", ".md", ".log", ".csv", ".json", ".yaml", ".yml", ".ini", ".py", ".sh", ".conf"}


class StorageError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def validate_name(name: str) -> str:
    if not isinstance(name, str) or not name or name != name.strip():
        raise StorageError(400, "名前が空、または前後に空白があります")
    if name in {".", ".."} or "/" in name or "\\" in name or _CONTROL.search(name):
        raise StorageError(400, "使用できない文字が含まれています")
    if len(name.encode("utf-8", "surrogatepass")) > MAX_NAME_BYTES:
        raise StorageError(400, "名前が長すぎます")
    if name.startswith(INTERNAL_PREFIX) or name in HIDDEN_NAMES:
        raise StorageError(400, "この名前は予約されています")
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        raise StorageError(400, "不正な文字が含まれています") from None
    return name


def kind_of(name: str, is_dir: bool) -> str:
    if is_dir:
        return "folder"
    ext = os.path.splitext(name)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in VIDEO_EXT:
        return "video"
    if ext in TEXT_EXT:
        return "text"
    return "file"


def mime_of(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


@dataclass
class Entry:
    name: str
    path: str
    is_dir: bool
    size: int
    mtime: float
    kind: str
    mime: str

    def as_dict(self) -> dict:
        return {
            "name": self.name, "path": self.path, "is_dir": self.is_dir, "size": self.size,
            "mtime": self.mtime, "kind": self.kind, "mime": self.mime,
        }


class Storage:
    def __init__(self, shared: Path, trash: Path):
        shared.mkdir(parents=True, exist_ok=True)
        trash.mkdir(parents=True, exist_ok=True)
        self.root = Path(os.path.realpath(shared))
        self.trash = Path(os.path.realpath(trash))
        if self.trash == self.root or self.root in self.trash.parents:
            raise SystemExit("設定エラー: ゴミ箱は共有フォルダの外に置いてください")

    # ---- パス解決 ----
    def _parts(self, rel: str) -> list[str]:
        if not isinstance(rel, str) or "\x00" in rel or "\\" in rel:
            raise StorageError(400, "不正なパスです")
        parts = []
        for p in rel.split("/"):
            if p in ("", "."):
                continue
            if p == "..":
                raise StorageError(400, "不正なパスです")
            if _CONTROL.search(p) or p.startswith(INTERNAL_PREFIX):
                raise StorageError(400, "不正なパスです")
            parts.append(p)
        return parts

    def _inside(self, real: str) -> bool:
        return real == str(self.root) or real.startswith(str(self.root) + os.sep)

    def resolve(self, rel: str, *, must_exist: bool = True) -> Path:
        full = self.root.joinpath(*self._parts(rel))
        # シンボリックリンクはリンク先が共有フォルダ内の場合のみ許可
        if not self._inside(os.path.realpath(full)):
            raise StorageError(403, "共有フォルダの外にはアクセスできません")
        if must_exist and not os.path.lexists(full):
            raise StorageError(404, "見つかりません")
        return full

    def rel(self, full: Path) -> str:
        r = os.path.relpath(full, self.root)
        return "" if r == "." else r.replace(os.sep, "/")

    def resolve_dir(self, rel: str) -> Path:
        full = self.resolve(rel)
        if not full.is_dir():
            raise StorageError(400, "フォルダではありません")
        return full

    def resolve_file(self, rel: str) -> Path:
        full = self.resolve(rel)
        if not full.is_file():
            raise StorageError(404, "ファイルが見つかりません")
        return full

    # ---- 一覧 ----
    def _entry(self, full: Path, name: str | None = None) -> Entry | None:
        name = name or full.name
        if name.startswith(INTERNAL_PREFIX) or name in HIDDEN_NAMES:
            return None
        try:
            if not self._inside(os.path.realpath(full)):
                return None
            st = full.stat()
        except OSError:
            return None
        is_dir = full.is_dir()
        return Entry(name, self.rel(full), is_dir, 0 if is_dir else st.st_size, st.st_mtime,
                     kind_of(name, is_dir), "" if is_dir else mime_of(name))

    def list(self, rel: str, sort: str = "name", order: str = "asc", q: str = "",
             recursive: bool = False, offset: int = 0, limit: int = 200) -> dict:
        base = self.resolve_dir(rel)
        q = q.strip().casefold()
        entries: list[Entry] = []
        if recursive and q:
            for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
                dirnames[:] = [d for d in dirnames if not d.startswith(INTERNAL_PREFIX)]
                for n in dirnames + filenames:
                    if q in n.casefold():
                        e = self._entry(Path(dirpath) / n)
                        if e:
                            entries.append(e)
                if len(entries) >= 2000:
                    break
        else:
            with os.scandir(base) as it:
                for de in it:
                    if q and q not in de.name.casefold():
                        continue
                    e = self._entry(base / de.name)
                    if e:
                        entries.append(e)
        reverse = order == "desc"
        keys = {
            "name": lambda e: e.name.casefold(),
            "mtime": lambda e: e.mtime,
            "size": lambda e: (e.size, e.name.casefold()),
        }
        key = keys.get(sort, keys["name"])
        folders = sorted((e for e in entries if e.is_dir),
                         key=(lambda e: e.name.casefold()) if sort == "size" else key, reverse=reverse)
        files = sorted((e for e in entries if not e.is_dir), key=key, reverse=reverse)
        allv = folders + files
        offset = max(0, offset)
        limit = max(1, min(limit, 1000))
        return {
            "path": self.rel(base),
            "parent": None if base == self.root else self.rel(base.parent),
            "total": len(allv),
            "entries": [e.as_dict() for e in allv[offset:offset + limit]],
        }

    def all_dirs(self, limit: int = 2000) -> list[str]:
        """移動先選択用の全フォルダ一覧。"""
        out = [""]
        for dirpath, dirnames, _ in os.walk(self.root, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(INTERNAL_PREFIX))
            for d in dirnames:
                full = Path(dirpath) / d
                if self._inside(os.path.realpath(full)):
                    out.append(self.rel(full))
            if len(out) >= limit:
                break
        return out

    def info(self, rel: str, with_hash: bool = False) -> dict:
        full = self.resolve(rel)
        e = self._entry(full)
        if e is None:
            raise StorageError(404, "見つかりません")
        d = e.as_dict()
        if e.is_dir:
            n = 0
            for _, dn, fn in os.walk(full, followlinks=False):
                n += len(dn) + len(fn)
            d["item_count"] = n
        elif with_hash:
            d["sha256"] = self.sha256(full)
        return d

    @staticmethod
    def sha256(full: Path) -> str:
        h = hashlib.sha256()
        with open(full, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    # ---- 変更操作 ----
    def unique_name(self, directory: Path, name: str) -> str:
        if not os.path.lexists(directory / name):
            return name
        stem, ext = os.path.splitext(name)
        if not stem:
            stem, ext = name, ""
        for i in range(1, 10000):
            cand = f"{stem} ({i}){ext}"
            if not os.path.lexists(directory / cand):
                return cand
        raise StorageError(409, "重複しない名前を作成できません")

    def mkdir(self, rel: str, name: str) -> str:
        parent = self.resolve_dir(rel)
        target = parent / validate_name(name)
        if os.path.lexists(target):
            raise StorageError(409, "同じ名前が既に存在します")
        os.mkdir(target)
        return self.rel(target)

    def rename(self, rel: str, new_name: str) -> str:
        src = self.resolve(rel)
        if src == self.root:
            raise StorageError(400, "共有フォルダ自体は変更できません")
        dst = src.parent / validate_name(new_name)
        if dst == src:
            return self.rel(src)
        if os.path.lexists(dst):
            raise StorageError(409, "同じ名前が既に存在します")
        os.rename(src, dst)
        return self.rel(dst)

    def move(self, rels: list[str], dest: str) -> list[str]:
        dest_dir = self.resolve_dir(dest)
        if not rels:
            raise StorageError(400, "対象がありません")
        plan = []
        for r in rels:
            src = self.resolve(r)
            if src == self.root:
                raise StorageError(400, "共有フォルダ自体は移動できません")
            if src.is_dir() and not src.is_symlink() and (dest_dir == src or src in dest_dir.parents):
                raise StorageError(400, "フォルダを自分自身の中には移動できません")
            target = dest_dir / src.name
            if os.path.lexists(target) and target != src:
                raise StorageError(409, f"移動先に同じ名前があります: {src.name}")
            plan.append((src, target))
        out = []
        for src, target in plan:
            if src != target:
                shutil.move(str(src), str(target))
            out.append(self.rel(target))
        return out

    def delete(self, rel: str) -> str:
        """ゴミ箱(共有フォルダ外)へ移動する。"""
        src = self.resolve(rel)
        if src == self.root:
            raise StorageError(400, "共有フォルダ自体は削除できません")
        bucket = self.trash / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        bucket.mkdir(parents=True)
        shutil.move(str(src), str(bucket / src.name))
        return str(bucket.name)

    # ---- アップロード ----
    def cleanup_partials(self) -> int:
        n = 0
        for dirpath, _, filenames in os.walk(self.root, followlinks=False):
            for f in filenames:
                if f.startswith(INTERNAL_PREFIX) and f.endswith(PART_SUFFIX):
                    try:
                        os.unlink(os.path.join(dirpath, f))
                        n += 1
                    except OSError:
                        pass
        return n

    def begin_upload(self, rel_dir: str, name: str, mode: str, size: int | None, max_bytes: int):
        directory = self.resolve_dir(rel_dir)
        validate_name(name)
        if mode not in ("fail", "overwrite", "rename"):
            raise StorageError(400, "modeが不正です")
        final = directory / name
        if os.path.lexists(final):
            if not self._inside(os.path.realpath(final)):
                raise StorageError(403, "共有フォルダの外にはアクセスできません")
            if mode == "fail":
                raise StorageError(409, "同名のファイルが既に存在します")
            if final.is_dir():
                raise StorageError(409, "同名のフォルダが存在します")
        if size is not None:
            if size > max_bytes:
                raise StorageError(413, f"ファイルが大きすぎます（上限 {max_bytes // (1024 * 1024)} MB）")
            if shutil.disk_usage(directory).free < size + 64 * 1024 * 1024:
                raise StorageError(507, "Ubuntu側の空き容量が不足しています")
        part = directory / f"{INTERNAL_PREFIX}{uuid.uuid4().hex}{PART_SUFFIX}"
        return directory, part

    def finish_upload(self, directory: Path, part: Path, name: str, mode: str, mtime_ms: int | None) -> str:
        final = directory / name
        if mode == "rename":
            final = directory / self.unique_name(directory, name)
        elif mode == "fail" and os.path.lexists(final):
            raise StorageError(409, "同名のファイルが既に存在します")
        elif os.path.lexists(final) and final.is_dir():
            raise StorageError(409, "同名のフォルダが存在します")
        if mtime_ms:
            try:
                ts = mtime_ms / 1000
                if 0 < ts <= time.time() + 86400:
                    os.utime(part, (ts, ts))
            except (OSError, ValueError, OverflowError):
                pass
        if final.is_symlink():
            os.unlink(final)
        os.replace(part, final)
        return self.rel(final)
