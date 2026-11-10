import io
import os
import struct
import zipfile
import zlib

from conftest import sha


def put(client, name, data, dir="", mode="fail"):
    return client.put("/api/upload", params={"dir": dir, "name": name, "mode": mode}, content=data)


def names(client, **params):
    r = client.get("/api/list", params=params)
    assert r.status_code == 200
    return [e["name"] for e in r.json()["entries"]]


def make_png() -> bytes:
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"\x00\xff\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_zip() -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("a.txt", "hello")
    return b.getvalue()


SAMPLES = {
    # JPEG: EXIF(APP1)を含むダミー。再圧縮されていないことをバイト一致で確認
    "photo.jpg": b"\xff\xd8\xff\xe1\x00\x10Exif\x00\x00MM\x00*\x00\x00\x00\x08" + os.urandom(5000) + b"\xff\xd9",
    "image.png": make_png(),
    "doc.pdf": b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n" + os.urandom(2000),
    "movie.mp4": b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + os.urandom(20000),
    "archive.zip": make_zip(),
    "note.txt": "日本語のテキスト\nline2\n".encode(),
    # HEICの実ファイルは用意できないため、ftyp heicヘッダを持つ合成バイナリ（実画像ではない）
    "synthetic.heic": b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + os.urandom(8000),
}


def test_upload_roundtrip_hash_all_formats(client, shared):
    for name, data in SAMPLES.items():
        r = put(client, name, data)
        assert r.status_code == 201, (name, r.text)
        assert r.json()["sha256"] == sha(data)
        assert (shared / name).read_bytes() == data  # 共有フォルダに実ファイルとして保存
        d = client.get("/api/file", params={"path": name, "download": "1"})
        assert d.status_code == 200 and sha(d.content) == sha(data)
        assert "attachment" in d.headers["content-disposition"]


def test_list_folders_navigation_and_parent(client, shared):
    (shared / "a" / "b").mkdir(parents=True)
    (shared / "a" / "b" / "f.txt").write_text("x")
    root = client.get("/api/list").json()
    assert root["parent"] is None and [e["name"] for e in root["entries"]] == ["a"]
    assert root["entries"][0]["is_dir"] is True
    sub = client.get("/api/list", params={"path": "a/b"}).json()
    assert sub["parent"] == "a" and sub["entries"][0]["name"] == "f.txt"
    assert sub["entries"][0]["size"] == 1 and sub["entries"][0]["kind"] == "text"
    assert client.get("/api/list", params={"path": "a/missing"}).status_code == 404
    assert client.get("/api/list", params={"path": "a/b/f.txt"}).status_code == 400


def test_ubuntu_side_changes_are_reflected(client, shared):
    assert names(client) == []
    (shared / "from_ubuntu.jpg").write_bytes(b"\xff\xd8abc")
    assert names(client) == ["from_ubuntu.jpg"]
    (shared / "from_ubuntu.jpg").unlink()
    assert names(client) == []


def test_mkdir_rename_move_delete(client, shared, settings):
    assert client.post("/api/mkdir", json={"path": "", "name": "docs"}).status_code == 201
    assert (shared / "docs").is_dir()
    assert client.post("/api/mkdir", json={"path": "", "name": "docs"}).status_code == 409
    put(client, "a.txt", b"hello")
    assert client.post("/api/rename", json={"path": "a.txt", "name": "b.txt"}).status_code == 200
    assert (shared / "b.txt").read_bytes() == b"hello" and not (shared / "a.txt").exists()
    assert client.post("/api/move", json={"paths": ["b.txt"], "dest": "docs"}).status_code == 200
    assert (shared / "docs" / "b.txt").read_bytes() == b"hello"
    put(client, "b.txt", b"other")
    assert client.post("/api/move", json={"paths": ["b.txt"], "dest": "docs"}).status_code == 409
    assert (shared / "docs" / "b.txt").read_bytes() == b"hello"  # 上書きされない
    assert client.post("/api/move", json={"paths": ["docs"], "dest": "docs"}).status_code == 400
    # 削除は確認が必須
    assert client.post("/api/delete", json={"path": "docs"}).status_code == 400
    assert client.post("/api/delete", json={"path": "docs", "confirm": "yes"}).status_code == 400
    assert (shared / "docs").exists()
    assert client.post("/api/delete", json={"path": "docs", "confirm": True}).status_code == 200
    assert not (shared / "docs").exists()
    trashed = list(settings.trash_dir.rglob("b.txt"))
    assert trashed, "ゴミ箱(共有フォルダ外)に退避される"


def test_overwrite_requires_explicit_mode(client, shared):
    put(client, "x.txt", b"one")
    assert put(client, "x.txt", b"two").status_code == 409
    assert (shared / "x.txt").read_bytes() == b"one"
    r = put(client, "x.txt", b"three", mode="rename")
    assert r.status_code == 201 and r.json()["name"] == "x (1).txt"
    assert put(client, "x.txt", b"four", mode="overwrite").status_code == 201
    assert (shared / "x.txt").read_bytes() == b"four" and (shared / "x (1).txt").read_bytes() == b"three"
    assert not list(shared.glob(".sharefile-*"))


def test_upload_into_new_nested_folder_and_multiple(client, shared):
    client.post("/api/mkdir", json={"path": "", "name": "trip"})
    for i in range(3):
        assert put(client, f"p{i}.jpg", os.urandom(100), dir="trip").status_code == 201
    assert names(client, path="trip") == ["p0.jpg", "p1.jpg", "p2.jpg"]


def test_sort_and_search(client, shared):
    (shared / "dir").mkdir()
    for n, size, m in (("b.txt", 5, 300), ("a.txt", 50, 100), ("C.txt", 1, 200)):
        p = shared / n
        p.write_bytes(b"x" * size)
        os.utime(p, (m, m))
    assert names(client) == ["dir", "a.txt", "b.txt", "C.txt"]
    assert names(client, order="desc") == ["dir", "C.txt", "b.txt", "a.txt"]
    assert names(client, sort="size") == ["dir", "C.txt", "b.txt", "a.txt"]
    assert names(client, sort="size", order="desc") == ["dir", "a.txt", "b.txt", "C.txt"]
    assert names(client, sort="mtime") == ["dir", "a.txt", "C.txt", "b.txt"]
    assert names(client, q="c.") == ["C.txt"]
    (shared / "dir" / "deep_a.png").write_bytes(b"1")
    assert names(client, q="deep") == []
    assert names(client, q="deep", recursive="1") == ["deep_a.png"]
    assert client.get("/api/list", params={"sort": "evil"}).status_code == 400


def test_pagination(client, shared):
    for i in range(30):
        (shared / f"f{i:02}.txt").write_text("x")
    d = client.get("/api/list", params={"limit": 10, "offset": 10}).json()
    assert d["total"] == 30 and len(d["entries"]) == 10 and d["entries"][0]["name"] == "f10.txt"


def test_preview_headers_and_range(client, shared):
    (shared / "t.txt").write_text("こんにちは")
    (shared / "i.png").write_bytes(SAMPLES["image.png"])
    (shared / "v.mp4").write_bytes(SAMPLES["movie.mp4"])
    (shared / "evil.html").write_text("<script>alert(1)</script>")
    t = client.get("/api/file", params={"path": "t.txt"})
    assert t.headers["content-type"].startswith("text/plain") and t.text == "こんにちは"
    assert client.get("/api/file", params={"path": "i.png"}).headers["content-type"] == "image/png"
    r = client.get("/api/file", params={"path": "v.mp4"}, headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and r.content == SAMPLES["movie.mp4"][:10]
    assert r.headers["accept-ranges"] == "bytes"
    h = client.get("/api/file", params={"path": "evil.html"})
    assert "attachment" in h.headers["content-disposition"]  # HTMLはインライン表示しない
    assert h.headers["x-content-type-options"] == "nosniff"


def test_info_hash(client, shared):
    put(client, "a.bin", b"abc")
    d = client.get("/api/info", params={"path": "a.bin", "hash": "1"}).json()
    assert d["sha256"] == sha(b"abc")


def test_japanese_and_special_filenames(client, shared):
    for n in ("写真 2024 (1).jpg", "a&b=c#d.txt", "emoji😀.png"):
        assert put(client, n, b"1").status_code == 201
        assert (shared / n).exists()
    r = client.get("/api/file", params={"path": "写真 2024 (1).jpg", "download": "1"})
    assert "filename*=utf-8''" in r.headers["content-disposition"]
