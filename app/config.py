import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config" / "sharefile.env"


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


@dataclass(frozen=True)
class Settings:
    shared_dir: Path
    trash_dir: Path
    log_dir: Path
    host: str
    port: int
    max_upload_bytes: int
    allowed_hosts: tuple[str, ...]


def _resolve(value: str) -> Path:
    p = Path(value).expanduser()
    return (p if p.is_absolute() else ROOT / p).resolve()


def load_settings(overrides: dict[str, str] | None = None) -> Settings:
    values = _read_env_file(CONFIG_FILE)
    values.update({k: v for k, v in os.environ.items() if k.startswith("SHAREFILE_")})
    if overrides:
        values.update(overrides)

    def get(key: str, default: str) -> str:
        return values.get(key, default) or default

    try:
        port = int(get("SHAREFILE_PORT", "8765"))
        max_mb = int(get("SHAREFILE_MAX_UPLOAD_MB", "10240"))
    except ValueError as e:
        raise SystemExit(f"設定エラー: 数値が不正です ({e})") from e
    if not 1 <= port <= 65535 or max_mb < 1:
        raise SystemExit("設定エラー: PORTまたはMAX_UPLOAD_MBが範囲外です")
    hosts = tuple(h.strip().lower() for h in values.get("SHAREFILE_ALLOWED_HOSTS", "").split(",") if h.strip())
    return Settings(
        shared_dir=_resolve(get("SHAREFILE_SHARED_DIR", "shared")),
        trash_dir=_resolve(get("SHAREFILE_TRASH_DIR", "trash")),
        log_dir=_resolve(get("SHAREFILE_LOG_DIR", "logs")),
        host=get("SHAREFILE_HOST", "127.0.0.1"),
        port=port,
        max_upload_bytes=max_mb * 1024 * 1024,
        allowed_hosts=hosts,
    )
