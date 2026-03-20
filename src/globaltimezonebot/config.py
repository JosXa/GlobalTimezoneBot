from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TelegramMode = Literal["polling", "webhook"]


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
class WebhookSettings:
    public_url: str
    path: str
    secret_token: str
    listen: str
    port: int

    @property
    def webhook_url(self) -> str:
        return f"{self.public_url}{self.path}"

    @property
    def url_path(self) -> str:
        return self.path.removeprefix("/")


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_path: Path
    geocoder_user_agent: str
    telegram_mode: TelegramMode = "polling"
    webhook: WebhookSettings | None = None

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

        raw_mode = os.getenv("TELEGRAM_MODE", "polling").strip().casefold()
        if raw_mode not in {"polling", "webhook"}:
            msg = "TELEGRAM_MODE must be either 'polling' or 'webhook'."
            raise RuntimeError(msg)

        webhook = _load_webhook_settings(raw_mode)
        telegram_mode: TelegramMode = "webhook" if webhook is not None else "polling"

        return cls(
            bot_token=bot_token,
            database_path=database_path,
            geocoder_user_agent=geocoder_user_agent,
            telegram_mode=telegram_mode,
            webhook=webhook,
        )


def _load_webhook_settings(mode: str) -> WebhookSettings | None:
    if mode == "polling":
        return None

    public_url = os.getenv("WEBHOOK_PUBLIC_URL", "").strip().rstrip("/")
    if not public_url:
        msg = "WEBHOOK_PUBLIC_URL is required when TELEGRAM_MODE=webhook."
        raise RuntimeError(msg)
    if not public_url.startswith("https://"):
        msg = "WEBHOOK_PUBLIC_URL must start with https:// for Telegram webhooks."
        raise RuntimeError(msg)
    if urlsplit(public_url).path not in {"", "/"}:
        msg = "WEBHOOK_PUBLIC_URL must not contain a path; use WEBHOOK_PATH instead."
        raise RuntimeError(msg)

    path = os.getenv("WEBHOOK_PATH", "/telegram").strip() or "/telegram"
    if not path.startswith("/"):
        path = f"/{path}"

    secret_token = os.getenv("WEBHOOK_SECRET_TOKEN", "").strip()
    if not secret_token:
        msg = "WEBHOOK_SECRET_TOKEN is required when TELEGRAM_MODE=webhook."
        raise RuntimeError(msg)

    listen = os.getenv("WEBHOOK_LISTEN", "0.0.0.0").strip() or "0.0.0.0"
    port_text = os.getenv("WEBHOOK_PORT", "8080").strip() or "8080"
    try:
        port = int(port_text)
    except ValueError as exc:
        msg = "WEBHOOK_PORT must be an integer."
        raise RuntimeError(msg) from exc

    return WebhookSettings(
        public_url=public_url,
        path=path,
        secret_token=secret_token,
        listen=listen,
        port=port,
    )
