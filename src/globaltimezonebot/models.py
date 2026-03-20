from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime, timedelta


class DisplayMode(str, Enum):
    PLACE = "place"
    COUNTRY = "country"
    TIMEZONE = "timezone"

    @property
    def label(self) -> str:
        return {
            DisplayMode.PLACE: "Full place",
            DisplayMode.COUNTRY: "Country",
            DisplayMode.TIMEZONE: "Timezone",
        }[self]


@dataclass(frozen=True, slots=True)
class LocationCandidate:
    place_name: str
    label: str
    country_name: str
    country_code: str | None
    latitude: float
    longitude: float
    timezone_name: str


@dataclass(frozen=True, slots=True)
class SavedLocation:
    id: int
    chat_id: int
    place_name: str
    label: str
    country_name: str
    country_code: str | None
    latitude: float
    longitude: float
    timezone_name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChatPreferences:
    chat_id: int
    display_mode: DisplayMode
    home_location_id: int | None


@dataclass(frozen=True, slots=True)
class TimeSnapshot:
    timezone_name: str
    current_time: datetime
    offset: timedelta

    @property
    def offset_label(self) -> str:
        total_minutes = int(self.offset.total_seconds() // 60)
        sign = "+" if total_minutes >= 0 else "-"
        hours, minutes = divmod(abs(total_minutes), 60)
        return f"UTC{sign}{hours:02d}:{minutes:02d}"


@dataclass(frozen=True, slots=True)
class SunSummary:
    sunrise: datetime | None
    sunset: datetime | None
    daylight: timedelta | None


@dataclass(frozen=True, slots=True)
class MeetingParticipantTime:
    label: str
    country_code: str | None
    local_time: datetime


@dataclass(frozen=True, slots=True)
class MeetingSuggestion:
    utc_time: datetime
    score: int
    participants: tuple[MeetingParticipantTime, ...]
