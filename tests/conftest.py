import hashlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from starlette.testclient import TestClient

from app.config import ROOT, Settings
from app.main import create_app

HDR = {"X-Requested-With": "ShareFile"}


def make_settings(tmp_path: Path, max_mb: int = 50) -> Settings:
    return Settings(
        shared_dir=tmp_path / "shared", trash_dir=tmp_path / "trash", log_dir=tmp_path / "logs",
        host="127.0.0.1", port=0, max_upload_bytes=max_mb * 1024 * 1024, allowed_hosts=(),
    )


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), base_url="http://localhost", headers=HDR) as c:
        yield c


@pytest.fixture
def shared(settings) -> Path:
    settings.shared_dir.mkdir(parents=True, exist_ok=True)
    return settings.shared_dir


@pytest.fixture
def live_server(tmp_path):
    """実プロセスでuvicornを起動（大容量・切断テスト用）。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, SHAREFILE_SHARED_DIR=str(tmp_path / "shared"), SHAREFILE_TRASH_DIR=str(tmp_path / "trash"),
               SHAREFILE_PORT=str(port), SHAREFILE_MAX_UPLOAD_MB="600")
    proc = subprocess.Popen([sys.executable, "-m", "app"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/api/config", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("server did not start")
    yield proc, port, tmp_path / "shared"
    proc.terminate()
    proc.wait(timeout=10)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
