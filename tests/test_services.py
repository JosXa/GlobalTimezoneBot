from __future__ import annotations

from datetime import datetime, timedelta, timezone

from globaltimezonebot.models import LocationCandidate
from globaltimezonebot.services import TimeService, _place_name


def test_offset_difference_between_berlin_and_new_york() -> None:
    service = TimeService()
    when = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

    difference = service.offset_difference("Europe/Berlin", "America/New_York", now=when)

    assert difference == timedelta(hours=-6)
    assert service.offset_difference_label(difference) == "6h behind"


def test_snapshot_formats_offset() -> None:
    service = TimeService()
    when = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

    snapshot = service.snapshot("Asia/Tokyo", now=when)

    assert snapshot.offset_label == "UTC+09:00"
    assert snapshot.current_time.tzinfo is not None


def test_place_name_prefers_province_before_country() -> None:
    address: dict[str, object] = {
        "province": "Tokyo",
        "country": "Japan",
    }

    assert _place_name(address) == "Tokyo"


def test_meeting_suggestions_favor_civilized_hours() -> None:
    service = TimeService()
    when = datetime(2026, 1, 15, 6, 10, tzinfo=timezone.utc)
    berlin = LocationCandidate(
        place_name="Berlin",
        label="Berlin, Germany",
        country_name="Germany",
        country_code="DE",
        latitude=52.52,
        longitude=13.405,
        timezone_name="Europe/Berlin",
    )
    tokyo = LocationCandidate(
        place_name="Tokyo",
        label="Tokyo, Japan",
        country_name="Japan",
        country_code="JP",
        latitude=35.6769,
        longitude=139.7639,
        timezone_name="Asia/Tokyo",
    )

    suggestions = service.meeting_suggestions([berlin, tokyo], now=when)

    assert len(suggestions) == 3
    best = suggestions[0]
    participant_hours = [participant.local_time.hour for participant in best.participants]
    assert participant_hours == [9, 17]


def test_sun_summary_has_daylight_window() -> None:
    service = TimeService()
    when = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    summary = service.sun_summary(52.52, 13.405, "Europe/Berlin", now=when)

    assert summary.sunrise is not None
    assert summary.sunset is not None
    assert summary.daylight is not None
    assert summary.daylight > timedelta(hours=8)
