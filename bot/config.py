from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    token: str
    admin_ids: List[int]
    database_path: Path
    paused: bool = False
    log_level: str = "INFO"
    log_file: Optional[Path] = None

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()
        token = os.getenv("BOT_TOKEN")
        if not token:
            raise RuntimeError("BOT_TOKEN environment variable is required")

        raw_admins = os.getenv("ADMIN_IDS", "")
        admin_ids = [int(admin_id.strip()) for admin_id in raw_admins.split(",") if admin_id.strip()]

        db_path_str = os.getenv("DATABASE_PATH", "reputation.db")
        database_path = Path(db_path_str)

        paused = os.getenv("BOT_PAUSED", "false").lower() in {"1", "true", "yes"}

        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

        log_file_raw = os.getenv("LOG_FILE")
        log_file: Optional[Path] = Path(log_file_raw).expanduser() if log_file_raw else None

        return cls(
            token=token,
            admin_ids=admin_ids,
            database_path=database_path,
            paused=paused,
            log_level=log_level,
            log_file=log_file,
        )
