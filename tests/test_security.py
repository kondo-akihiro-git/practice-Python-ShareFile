import os
import socket
import time

import httpx
import pytest
from starlette.testclient import TestClient

from app.main import create_app
from conftest import HDR


def put(client, name, data, dir="", mode="fail"):
    return client.put("/api/upload", params={"dir": dir, "name": name, "mode": mode}, content=data)


@pytest.fixture
def outside(tmp_path):
    out = tmp_path / "outside"
    out.mkdir()
    (out / "secret.txt").write_text("TOP SECRET")
    return out


TRAVERSAL = ["../outside/secret.txt", "..", "a/../../outside", "/etc/passwd", "%2e%2e/outside/secret.txt",
             "....//outside", "a\\..\\..\\x", "x\x00y", "..%2f..%2foutside"]


@pytest.mark.parametrize("p", TRAVERSAL)
def test_path_traversal_rejected(client, shared, outside, p):
    for url in ("/api/list", "/api/file", "/api/info"):
        r = client.get(url, params={"path": p})
        assert r.status_code in (400, 403, 404), (url, p, r.status_code)
        assert b"TOP SECRET" not in r.content
    assert put(client, "evil.txt", b"x", dir=p).status_code in (400, 403, 404)
    assert client.post("/api/delete", json={"path": p, "confirm": True}).status_code in (400, 403, 404)
    assert client.post("/api/rename", json={"path": p, "name": "z"}).status_code in (400, 403, 404)
    assert client.post("/api/move", json={"paths": [p], "dest": ""}).status_code in (400, 403, 404)
    assert client.post("/api/move", json={"paths": ["ok"], "dest": p}).status_code in (400, 403, 404)
    assert (outside / "secret.txt").read_text() == "TOP SECRET"


def test_raw_url_traversal(client, shared, outside):
    for u in ("/static/../app/main.py", "/static/%2e%2e/app/main.py", "/static/..%2fconfig/sharefile.env"):
        r = client.get(u)
        assert r.status_code == 404 or b"SHAREFILE" not in r.content


def test_symlink_escape_blocked(client, shared, outside):
    (shared / "link_file").symlink_to(outside / "secret.txt")
    (shared / "link_dir").symlink_to(outside, target_is_directory=True)
    (shared / "inner").mkdir()
    (shared / "inner" / "ok.txt").write_text("ok")
    (shared / "link_inner").symlink_to(shared / "inner", target_is_directory=True)
    listed = [e["name"] for e in client.get("/api/list").json()["entries"]]
    assert "link_file" not in listed and "link_dir" not in listed  # 外を指すリンクは見えない
    assert "link_inner" in listed  # 共有フォルダ内を指すリンクは許可
    for p in ("link_file", "link_dir", "link_dir/secret.txt"):
        for url in ("/api/file", "/api/info", "/api/list"):
            r = client.get(url, params={"path": p})
            assert r.status_code == 403 and b"TOP SECRET" not in r.content
    assert put(client, "w.txt", b"x", dir="link_dir").status_code == 403
    assert not (outside / "w.txt").exists()
    assert client.post("/api/delete", json={"path": "link_dir/secret.txt", "confirm": True}).status_code == 403
    assert client.post("/api/move", json={"paths": ["inner/ok.txt"], "dest": "link_dir"}).status_code == 403
    assert client.post("/api/rename", json={"path": "link_dir/secret.txt", "name": "n"}).status_code == 403
    assert (outside / "secret.txt").read_text() == "TOP SECRET"
    assert client.get("/api/file", params={"path": "link_inner/ok.txt"}).text == "ok"


def test_upload_overwrite_through_symlink_blocked(client, shared, outside):
    (shared / "victim.txt").symlink_to(outside / "secret.txt")
    assert put(client, "victim.txt", b"HACK", mode="overwrite").status_code == 403
    assert (outside / "secret.txt").read_text() == "TOP SECRET"


@pytest.mark.parametrize("name", ["", " ", ".", "..", "a/b", "a\\b", "x\x00y", "\n", "a" * 300, ".sharefile-x.part", " lead", "trail "])
def test_invalid_names_rejected(client, shared, name):
    assert put(client, name, b"x").status_code == 400
    assert client.post("/api/mkdir", json={"path": "", "name": name}).status_code == 400
    put(client, "ok.txt", b"1")
    assert client.post("/api/rename", json={"path": "ok.txt", "name": name}).status_code == 400
    assert client.post("/api/rename", json={"path": "ok.txt", "name": 123}).status_code == 400


def test_internal_files_hidden_and_inaccessible(client, shared):
    (shared / ".sharefile-abc.part").write_text("partial")
    assert client.get("/api/list").json()["entries"] == []
    assert client.get("/api/file", params={"path": ".sharefile-abc.part"}).status_code == 400


def test_disallowed_methods(client, shared):
    put(client, "a.txt", b"1")
    assert client.post("/api/list").status_code == 405
    assert client.delete("/api/file", params={"path": "a.txt"}).status_code == 405
    assert client.put("/api/mkdir", json={}).status_code == 405
    assert client.get("/api/delete", params={"path": "a.txt"}).status_code == 405
    assert client.post("/api/upload", content=b"x").status_code == 405
    assert client.patch("/api/rename").status_code == 405
    assert (shared / "a.txt").exists()


def test_csrf_protection(shared, settings):
    with TestClient(create_app(settings), base_url="http://localhost") as c:  # 独自ヘッダなし
        assert c.post("/api/mkdir", json={"path": "", "name": "x"}).status_code == 403
        assert c.post("/api/mkdir", data="path=&name=x", headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 403
        assert c.put("/api/upload", params={"dir": "", "name": "x"}, content=b"1").status_code == 403
        # 別オリジンからの送信
        r = c.post("/api/mkdir", json={"path": "", "name": "x"}, headers={**HDR, "Origin": "https://evil.example"})
        assert r.status_code == 403
        r = c.post("/api/mkdir", json={"path": "", "name": "x"}, headers={**HDR, "Sec-Fetch-Site": "cross-site"})
        assert r.status_code == 403
        ok = c.post("/api/mkdir", json={"path": "", "name": "x"}, headers={**HDR, "Origin": "http://localhost:8765"})
        assert ok.status_code == 201


def test_host_header_allowlist(shared, settings):
    with TestClient(create_app(settings), headers=HDR) as c:
        for host, code in (("localhost:8765", 200), ("127.0.0.1", 200), ("pc.tail1234.ts.net", 200),
                           ("100.101.102.103:8765", 200), ("evil.example.com", 421), ("192.168.1.5", 421),
                           ("localhost.evil.com", 421)):
            assert c.get("/api/config", headers={"Host": host}).status_code == code, host


def test_security_headers_on_app(client):
    r = client.get("/")
    assert r.status_code == 200 and "シェアファイル" in r.text
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors" in r.headers["content-security-policy"]


def test_malformed_requests_do_not_crash(client, shared):
    assert client.post("/api/mkdir", content=b"{not json", headers={"Content-Type": "application/json"}).status_code == 400
    assert client.post("/api/mkdir", content=b"[1,2]").status_code == 400
    assert client.post("/api/move", json={"paths": "x", "dest": ""}).status_code == 400
    assert client.post("/api/move", json={"paths": [1], "dest": ""}).status_code == 400
    assert client.post("/api/mkdir", content=b"x" * (2 * 1024 * 1024)).status_code == 413
    assert client.get("/api/list", params={"offset": "abc"}).status_code == 400
    assert client.get("/api/list", params={"limit": "-5"}).status_code == 200
    assert client.put("/api/upload", params={"dir": "", "name": "a"}, content=b"1", headers={"x-last-modified": "zzz"}).status_code == 201
    assert client.put("/api/upload", params={"dir": "", "name": "b", "mode": "bogus"}, content=b"1").status_code == 400
    assert client.get("/nonexistent").status_code == 404
    assert client.get("/api/config").status_code == 200


def test_upload_size_limit(shared, settings):
    from conftest import make_settings
    s = make_settings(settings.shared_dir.parent / "s2", max_mb=1)
    with TestClient(create_app(s), base_url="http://localhost", headers=HDR) as c:
        r = c.put("/api/upload", params={"dir": "", "name": "big.bin"}, content=os.urandom(2 * 1024 * 1024))
        assert r.status_code == 413
        assert list(s.shared_dir.iterdir()) == []  # 不完全ファイルも残らない
        assert c.put("/api/upload", params={"dir": "", "name": "ok.bin"}, content=os.urandom(900 * 1024)).status_code == 201


def _raw(port, head: bytes, body: bytes = b"", close_early=True):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(head + body)
    if close_early:
        s.close()
    return s


def test_interrupted_upload_leaves_no_file(live_server):
    proc, port, shared = live_server
    head = (b"PUT /api/upload?dir=&name=partial.bin&mode=fail HTTP/1.1\r\nHost: localhost\r\n"
            b"X-Requested-With: ShareFile\r\nContent-Length: 5000000\r\n\r\n")
    _raw(port, head, os.urandom(1_000_000))  # 途中で切断
    time.sleep(1.0)
    assert [p.name for p in shared.iterdir()] == []
    assert httpx.get(f"http://127.0.0.1:{port}/api/list").status_code == 200  # サーバー健在


def test_oversized_declared_length_rejected_early(live_server):
    proc, port, shared = live_server
    head = (b"PUT /api/upload?dir=&name=huge.bin&mode=fail HTTP/1.1\r\nHost: localhost\r\n"
            b"X-Requested-With: ShareFile\r\nContent-Length: 999999999999\r\n\r\n")
    s = _raw(port, head, close_early=False)
    assert s.recv(200).startswith(b"HTTP/1.1 413")
    s.close()
    assert list(shared.iterdir()) == []


def test_garbage_http_does_not_kill_server(live_server):
    proc, port, _ = live_server
    for junk in (b"GARBAGE\r\n\r\n", b"\x00\x01\x02" * 100, b"GET /%%%% HTTP/1.1\r\nHost: x\r\n\r\n"):
        _raw(port, junk)
    time.sleep(0.3)
    assert proc.poll() is None
    assert httpx.get(f"http://127.0.0.1:{port}/api/config").status_code == 200
