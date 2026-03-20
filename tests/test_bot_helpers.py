from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from telegram import BotCommand

from globaltimezonebot.bot import (
    _clip,
    _commands_match,
    _flag_emoji,
    _load_commands_file,
    _manage_location_button_label,
    _meeting_button_label,
    _parse_display_mode,
)
from globaltimezonebot.models import DisplayMode, SavedLocation

if TYPE_CHECKING:
    from pathlib import Path


def test_flag_emoji_builds_regional_indicator_flag() -> None:
    assert _flag_emoji("JP") == "🇯🇵"


def test_parse_display_mode_accepts_short_values() -> None:
    assert _parse_display_mode("timezone") is DisplayMode.TIMEZONE
    assert _parse_display_mode("country") is DisplayMode.COUNTRY


def test_clip_adds_ellipsis_when_needed() -> None:
    assert _clip("this label is too long", 10) == "this labe…"


def test_load_commands_file_parses_expected_format(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.txt"
    commands_file.write_text("start - Welcome\nhelp - Assistance\n", encoding="utf-8")

    commands = _load_commands_file(commands_file)

    assert commands == [
        BotCommand(command="start", description="Welcome"),
        BotCommand(command="help", description="Assistance"),
    ]


def test_commands_match_compares_command_and_description() -> None:
    current = [BotCommand(command="start", description="Welcome")]
    desired = [BotCommand(command="start", description="Welcome")]
    changed = [BotCommand(command="start", description="Different")]

    assert _commands_match(current, desired) is True
    assert _commands_match(current, changed) is False


def test_manage_location_button_label_uses_place_name() -> None:
    location = SavedLocation(
        id=1,
        chat_id=62056065,
        place_name="Reykjavik",
        label="Reykjavik, Iceland",
        country_name="Iceland",
        country_code="IS",
        latitude=64.146,
        longitude=-21.9422,
        timezone_name="Atlantic/Reykjavik",
        created_at=datetime.now(tz=timezone.utc),
    )

    label = _manage_location_button_label(location)

    assert label == "🇮🇸 Reykjavik"


def test_meeting_button_label_reflects_selection() -> None:
    location = SavedLocation(
        id=1,
        chat_id=62056065,
        place_name="Reykjavik",
        label="Reykjavik, Iceland",
        country_name="Iceland",
        country_code="IS",
        latitude=64.146,
        longitude=-21.9422,
        timezone_name="Atlantic/Reykjavik",
        created_at=datetime.now(tz=timezone.utc),
    )

    selected = _meeting_button_label(location, selected=True)
    unselected = _meeting_button_label(location, selected=False)

    assert selected.startswith("✅ 🇮🇸")
    assert unselected.startswith("⬜ 🇮🇸")
