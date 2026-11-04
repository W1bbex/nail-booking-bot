import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse
from dotenv import load_dotenv

logger = logging.getLogger("core.config")

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
CONFIG_PATH = BASE_DIR / "config.json"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "studio.db"

# Load environment variables
load_dotenv(dotenv_path=ENV_PATH)


class Settings:
    def __init__(self) -> None:
        # Tier 1: Secrets from environment
        self.bot_token: str = os.getenv("BOT_TOKEN", "").strip()
        self.secret_key: str = os.getenv("SECRET_KEY", "dev-secret-key").strip()

        # Tier 2: Operational config from JSON
        if not CONFIG_PATH.is_file():
            logger.critical(f"Missing configuration file: {CONFIG_PATH}")
            sys.exit(1)

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw_config: Dict[str, Any] = json.load(f)
        except Exception as e:
            logger.critical(f"Failed to parse config.json: {e}")
            sys.exit(1)

        self.salon: Dict[str, Any] = raw_config.get("salon", {})
        self.server: Dict[str, Any] = raw_config.get("server", {})
        self.booking: Dict[str, Any] = raw_config.get("booking", {})
        self.admin_telegram_ids: List[int] = [
            int(x) for x in raw_config.get("admin_telegram_ids", [])
        ]
        self.initial_masters: List[Dict[str, Any]] = raw_config.get("initial_masters", [])
        self.initial_services: List[Dict[str, Any]] = raw_config.get("initial_services", [])

        # Server convenience
        self.host: str = self.server.get("host", "127.0.0.1")
        self.port: int = int(self.server.get("port", 8080))
        self.public_url: str = self.server.get("public_url", f"http://{self.host}:{self.port}")
        self.dev_mode: bool = bool(self.server.get("dev_mode", False))
        if os.getenv("NAIL_LOCAL_PREVIEW") == "1":
            self.host = "127.0.0.1"
            self.dev_mode = True
            self.public_url = f"http://127.0.0.1:{self.port}"
        if self.dev_mode and self.host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("dev_mode разрешён только на локальном интерфейсе")

        # Explicit trusted CORS origins (no wildcard regex in production)
        parsed_pub = urlparse(self.public_url)
        pub_origin = (
            f"{parsed_pub.scheme}://{parsed_pub.netloc}"
            if parsed_pub.scheme and parsed_pub.netloc
            else ""
        )
        configured_origins = self.server.get("allowed_origins", [])
        origins_set = {"https://web.telegram.org"}
        if pub_origin:
            origins_set.add(pub_origin)
        for o in configured_origins:
            if isinstance(o, str) and o.strip():
                origins_set.add(o.strip().rstrip("/"))
        if self.dev_mode or self.host in ("127.0.0.1", "::1", "localhost"):
            origins_set.add(f"http://127.0.0.1:{self.port}")
            origins_set.add(f"http://localhost:{self.port}")
        self.allowed_origins: List[str] = sorted(origins_set)

        # Database connection URL
        self.database_url: str = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"

    def is_admin(self, telegram_id: int | None) -> bool:
        if not telegram_id:
            return False
        return int(telegram_id) in self.admin_telegram_ids


settings = Settings()
