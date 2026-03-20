from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_path: Path
    geocoder_user_agent: str

    @classmethod
    def from_env(cls) -> Settings:
        _load_dotenv(PROJECT_ROOT / ".env")

        bot_token = os.getenv("BOT_TOKEN") or os.getenv("TG_TOKEN")
        if not bot_token:
            msg = "BOT_TOKEN is missing. Put it in .env or the environment."
            raise RuntimeError(msg)

        database_value = os.getenv("GTB_DATABASE_PATH", ".data/globaltimezonebot.sqlite3")
        database_path = Path(database_value)
        if not database_path.is_absolute():
            database_path = PROJECT_ROOT / database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)

        geocoder_user_agent = os.getenv(
            "GEOCODER_USER_AGENT",
            "globaltimezonebot/2026.03 (revived timezone lookup bot)",
        )
        return cls(
            bot_token=bot_token,
            database_path=database_path,
            geocoder_user_agent=geocoder_user_agent,
        )
