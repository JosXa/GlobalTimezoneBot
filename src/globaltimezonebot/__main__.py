from __future__ import annotations

from globaltimezonebot.bot import run_bot
from globaltimezonebot.config import Settings


def main() -> None:
    settings = Settings.from_env()
    run_bot(settings)


if __name__ == "__main__":
    main()
