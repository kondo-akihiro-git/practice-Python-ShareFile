import uvicorn

from .config import load_settings
from .main import create_app

if __name__ == "__main__":
    s = load_settings()
    uvicorn.run(create_app(s), host=s.host, port=s.port, log_level="info", server_header=False,
                timeout_keep_alive=30)
