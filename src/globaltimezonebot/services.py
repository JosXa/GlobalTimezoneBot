from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pycountry
from astral import Observer
from astral.sun import sun
from geopy import Location
from geopy.adapters import AdapterHTTPError
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

from globaltimezonebot.models import (
    LocationCandidate,
    MeetingParticipantTime,
    MeetingSuggestion,
    SunSummary,
    TimeSnapshot,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from globaltimezonebot.models import SavedLocation


class LocationLookupError(RuntimeError):
    """Raised when location lookup fails for expected reasons."""


class TimeService:
    def __init__(self) -> None:
        self._timezone_finder = TimezoneFinder(in_memory=True)
        self._timezone_cache: dict[tuple[float, float], str] = {}

    def resolve_timezone_name(self, latitude: float, longitude: float) -> str:
        key = (round(latitude, 4), round(longitude, 4))
        if key in self._timezone_cache:
            return self._timezone_cache[key]

        timezone_name = self._timezone_finder.timezone_at(lng=longitude, lat=latitude)
        if timezone_name is None:
            timezone_name = self._timezone_finder.certain_timezone_at(
                lng=longitude,
                lat=latitude,
            )
        if timezone_name is None:
            msg = f"No timezone found for coordinates ({latitude}, {longitude})"
            raise LocationLookupError(msg)
        self._timezone_cache[key] = timezone_name
        return timezone_name

    def snapshot(self, timezone_name: str, now: datetime | None = None) -> TimeSnapshot:
        current_utc = now.astimezone(timezone.utc) if now else datetime.now(tz=timezone.utc)
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            msg = f"Unknown timezone {timezone_name!r}"
            raise LocationLookupError(msg) from exc
        current_time = current_utc.astimezone(zone)
        offset = current_time.utcoffset()
        if offset is None:
            msg = f"Timezone {timezone_name!r} has no UTC offset"
            raise LocationLookupError(msg)
        return TimeSnapshot(
            timezone_name=timezone_name,
            current_time=current_time,
            offset=offset,
        )

    def sun_summary(
        self,
        latitude: float,
        longitude: float,
        timezone_name: str,
        now: datetime | None = None,
    ) -> SunSummary:
        snapshot = self.snapshot(timezone_name, now=now)
        observer = Observer(latitude=latitude, longitude=longitude)
        zone = ZoneInfo(timezone_name)
        try:
            sun_times = sun(
                observer,
                date=snapshot.current_time.date(),
                tzinfo=zone,
            )
        except ValueError:
            return SunSummary(sunrise=None, sunset=None, daylight=None)
        sunrise = sun_times.get("sunrise")
        sunset = sun_times.get("sunset")
        if not isinstance(sunrise, datetime) or not isinstance(sunset, datetime):
            return SunSummary(sunrise=None, sunset=None, daylight=None)
        return SunSummary(
            sunrise=sunrise,
            sunset=sunset,
            daylight=sunset - sunrise,
        )

    def sky_emoji(
        self,
        latitude: float,
        longitude: float,
        timezone_name: str,
        now: datetime | None = None,
    ) -> str:
        snapshot = self.snapshot(timezone_name, now=now)
        summary = self.sun_summary(latitude, longitude, timezone_name, now=now)
        if summary.sunrise is None or summary.sunset is None:
            hour = snapshot.current_time.hour
            if 6 <= hour < 18:
                return "☀️"
            return "🌙"

        current_time = snapshot.current_time
        sunrise = summary.sunrise
        sunset = summary.sunset
        if current_time < sunrise or current_time >= sunset:
            return "🌙"
        if current_time <= sunrise + timedelta(hours=1):
            return "🌅"
        if current_time >= sunset - timedelta(hours=1):
            return "🌆"
        return "☀️"

    def offset_difference(
        self,
        base_timezone: str,
        other_timezone: str,
        now: datetime | None = None,
    ) -> timedelta:
        base_snapshot = self.snapshot(base_timezone, now=now)
        other_snapshot = self.snapshot(other_timezone, now=now)
        return other_snapshot.offset - base_snapshot.offset

    @staticmethod
    def offset_difference_label(difference: timedelta) -> str:
        total_minutes = int(difference.total_seconds() // 60)
        if total_minutes == 0:
            return "same local time"
        hours, minutes = divmod(abs(total_minutes), 60)
        ahead_or_behind = "ahead" if total_minutes > 0 else "behind"
        if minutes == 0:
            return f"{hours}h {ahead_or_behind}"
        return f"{hours}h {minutes}m {ahead_or_behind}"

    def meeting_suggestions(
        self,
        locations: Sequence[LocationCandidate | SavedLocation],
        *,
        now: datetime | None = None,
        horizon_hours: int = 24,
        step_minutes: int = 30,
        count: int = 3,
    ) -> list[MeetingSuggestion]:
        if len(locations) < 2:
            return []

        base_utc = now.astimezone(timezone.utc) if now else datetime.now(tz=timezone.utc)
        minute_bucket = (base_utc.minute // step_minutes) * step_minutes
        start_utc = base_utc.replace(minute=minute_bucket, second=0, microsecond=0)
        if start_utc < base_utc:
            start_utc += timedelta(minutes=step_minutes)

        suggestions: list[MeetingSuggestion] = []
        total_steps = max(1, (horizon_hours * 60) // step_minutes)
        for step in range(total_steps):
            candidate_utc = start_utc + timedelta(minutes=step * step_minutes)
            participant_times: list[MeetingParticipantTime] = []
            scores: list[int] = []
            for location in locations:
                snapshot = self.snapshot(location.timezone_name, now=candidate_utc)
                participant_times.append(
                    MeetingParticipantTime(
                        label=location.place_name,
                        country_code=location.country_code,
                        local_time=snapshot.current_time,
                    )
                )
                scores.append(_meeting_score(snapshot.current_time))
            score = min(scores) * 5 + sum(scores)
            suggestions.append(
                MeetingSuggestion(
                    utc_time=candidate_utc,
                    score=score,
                    participants=tuple(participant_times),
                )
            )

        suggestions.sort(key=lambda item: (-item.score, item.utc_time))
        return suggestions[:count]


class GeocodingService:
    def __init__(self, *, user_agent: str, time_service: TimeService) -> None:
        self._geocoder = Nominatim(user_agent=user_agent)
        self._time_service = time_service

    async def search(self, query: str, *, limit: int = 5) -> list[LocationCandidate]:
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        try:
            raw_results = await asyncio.to_thread(
                self._geocoder.geocode,
                cleaned_query,
                exactly_one=False,
                addressdetails=True,
                language="en",
                limit=limit,
            )
        except (AdapterHTTPError, OSError, ValueError) as exc:
            msg = "Geocoding lookup failed"
            raise LocationLookupError(msg) from exc

        return self._to_candidates(raw_results)

    async def reverse(self, *, latitude: float, longitude: float) -> list[LocationCandidate]:
        try:
            raw_result = await asyncio.to_thread(
                self._geocoder.reverse,
                (latitude, longitude),
                exactly_one=False,
                addressdetails=True,
                language="en",
            )
        except (AdapterHTTPError, OSError, ValueError) as exc:
            msg = "Reverse geocoding lookup failed"
            raise LocationLookupError(msg) from exc

        return self._to_candidates(raw_result)

    def _to_candidates(self, raw_results: object) -> list[LocationCandidate]:
        if raw_results is None:
            return []
        if isinstance(raw_results, Location):
            results = [raw_results]
        elif isinstance(raw_results, list):
            results = [result for result in raw_results if isinstance(result, Location)]
        else:
            return []

        deduped: list[LocationCandidate] = []
        seen: set[tuple[str, str, int, int]] = set()
        for result in results:
            candidate = self._candidate_from_location(result)
            if candidate is None:
                continue
            key = (
                candidate.label.casefold(),
                candidate.timezone_name,
                round(candidate.latitude * 10_000),
                round(candidate.longitude * 10_000),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    def _candidate_from_location(self, location: Location) -> LocationCandidate | None:
        raw = location.raw
        address = raw.get("address") if isinstance(raw, dict) else None
        if not isinstance(address, dict):
            return None

        latitude = float(location.latitude)
        longitude = float(location.longitude)
        try:
            timezone_name = self._time_service.resolve_timezone_name(latitude, longitude)
        except LocationLookupError:
            return None

        country_code = _normalize_country_code(address.get("country_code"))
        fallback_country = str(address.get("country") or "Unknown country")
        country_name = _country_name(country_code) or fallback_country
        place_name = _place_name(address)
        label = _location_label(place_name, address, country_name)
        return LocationCandidate(
            place_name=place_name,
            label=label,
            country_name=country_name,
            country_code=country_code,
            latitude=latitude,
            longitude=longitude,
            timezone_name=timezone_name,
        )


@lru_cache(maxsize=512)
def _country_name(country_code: str | None) -> str | None:
    if country_code is None:
        return None
    country = pycountry.countries.get(alpha_2=country_code)
    if country is None:
        return None
    return str(country.name)


def _normalize_country_code(raw_country_code: object) -> str | None:
    if not isinstance(raw_country_code, str):
        return None
    country_code = raw_country_code.strip().upper()
    return country_code or None


def _place_name(address: dict[str, object]) -> str:
    for key in (
        "city",
        "town",
        "village",
        "municipality",
        "hamlet",
        "suburb",
        "province",
        "county",
        "state_district",
        "state",
    ):
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    country = address.get("country")
    if isinstance(country, str) and country.strip():
        return country.strip()
    return "Unknown place"


def _location_label(place_name: str, address: dict[str, object], country_name: str) -> str:
    parts: list[str] = [place_name]
    for key in ("state", "region", "county"):
        value = address.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in parts:
            parts.append(value.strip())
            break
    if country_name not in parts:
        parts.append(country_name)
    return ", ".join(parts)


def _meeting_score(local_time: datetime) -> int:
    minutes = local_time.hour * 60 + local_time.minute
    if time(9, 0) <= local_time.time() <= time(17, 30):
        base = 120
    elif time(8, 0) <= local_time.time() <= time(20, 0):
        base = 70
    elif time(7, 0) <= local_time.time() <= time(22, 0):
        base = 20
    else:
        base = -160

    distance_from_midday = abs(minutes - (13 * 60)) // 15
    weekend_penalty = 40 if local_time.weekday() >= 5 else 0
    return base - distance_from_midday * 4 - weekend_penalty


def as_candidate(location: SavedLocation) -> LocationCandidate:
    return LocationCandidate(
        place_name=location.place_name,
        label=location.label,
        country_name=location.country_name,
        country_code=location.country_code,
        latitude=location.latitude,
        longitude=location.longitude,
        timezone_name=location.timezone_name,
    )
