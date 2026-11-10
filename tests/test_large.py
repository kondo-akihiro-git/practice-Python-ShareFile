import hashlib
import os
import time

import httpx

MB = 1024 * 1024


def _rss_hwm_mb(pid: int) -> float:
    for line in open(f"/proc/{pid}/status"):
        if line.startswith("VmHWM"):
            return int(line.split()[1]) / 1024
    raise RuntimeError


def test_large_upload_and_download_constant_memory(live_server):
    proc, port, shared = live_server
    base = f"http://127.0.0.1:{port}"
    size_mb = 400
    h = hashlib.sha256()

    def gen():
        block = os.urandom(MB)
        for i in range(size_mb):
            b = block[:-8] + i.to_bytes(8, "big")
            h.update(b)
            yield b

    before = _rss_hwm_mb(proc.pid)
    t = time.time()
    r = httpx.put(f"{base}/api/upload", params={"dir": "", "name": "large.bin"}, content=gen(),
                  headers={"X-Requested-With": "ShareFile", "Content-Length": str(size_mb * MB)}, timeout=300)
    assert r.status_code == 201, r.text
    assert r.json()["sha256"] == h.hexdigest()
    assert (shared / "large.bin").stat().st_size == size_mb * MB
    after_up = _rss_hwm_mb(proc.pid)

    dh = hashlib.sha256()
    with httpx.stream("GET", f"{base}/api/file", params={"path": "large.bin", "download": "1"}, timeout=300) as resp:
        assert resp.status_code == 200
        for chunk in resp.iter_bytes(MB):
            dh.update(chunk)
    assert dh.hexdigest() == h.hexdigest()
    after_dl = _rss_hwm_mb(proc.pid)
    print(f"\n{size_mb}MB up/down in {time.time() - t:.1f}s; server RSS peak: before={before:.0f}MB up={after_up:.0f}MB down={after_dl:.0f}MB")
    assert after_dl - before < 100, "メモリ使用量がファイルサイズに比例して増えている"
