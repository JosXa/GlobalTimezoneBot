from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from globaltimezonebot.bot import GlobalTimezoneBot
from globaltimezonebot.config import Settings

if TYPE_CHECKING:
    from pathlib import Path

    from telegram import InlineKeyboardMarkup


@dataclass(slots=True)
class FakeCallbackQuery:
    text: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    reply_markup: InlineKeyboardMarkup | None = None

    async def edit_message_text(
        self,
        text: str,
        *,
        disable_web_page_preview: bool,
        parse_mode: str,
        reply_markup: InlineKeyboardMarkup | None,
    ) -> None:
        self.text = text
        self.parse_mode = parse_mode
        self.disable_web_page_preview = disable_web_page_preview
        self.reply_markup = reply_markup


@dataclass(slots=True)
class FakeMessage:
    text: str | None = None
    parse_mode: str | None = None
    disable_web_page_preview: bool | None = None
    reply_markup: object | None = None

    async def reply_text(
        self,
        text: str,
        *,
        disable_web_page_preview: bool,
        parse_mode: str,
        reply_markup: object,
    ) -> None:
        self.text = text
        self.parse_mode = parse_mode
        self.disable_web_page_preview = disable_web_page_preview
        self.reply_markup = reply_markup


@dataclass(slots=True)
class FakeUpdate:
    callback_query: FakeCallbackQuery | None
    effective_message: FakeMessage | None


def _bot(tmp_path: Path) -> GlobalTimezoneBot:
    settings = Settings(
        bot_token="test-token",
        database_path=tmp_path / "bot.sqlite3",
        geocoder_user_agent="globaltimezonebot-tests",
    )
    return GlobalTimezoneBot(settings)


async def test_present_result_text_edits_existing_callback_message(tmp_path: Path) -> None:
    bot = _bot(tmp_path)
    callback_query = FakeCallbackQuery()
    message = FakeMessage()
    update = FakeUpdate(callback_query=callback_query, effective_message=message)

    await bot._present_result_text(
        callback_query=update.callback_query,
        message=update.effective_message,
        text="hello",
        inline_reply_markup=None,
    )

    assert callback_query.text == "hello"
    assert message.text is None


async def test_present_result_text_replies_for_normal_message(tmp_path: Path) -> None:
    bot = _bot(tmp_path)
    message = FakeMessage()
    update = FakeUpdate(callback_query=None, effective_message=message)

    await bot._present_result_text(
        callback_query=update.callback_query,
        message=update.effective_message,
        text="hello",
        inline_reply_markup=None,
    )

    assert message.text == "hello"
