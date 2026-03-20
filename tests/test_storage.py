from __future__ import annotations

from typing import TYPE_CHECKING

from globaltimezonebot.models import DisplayMode, LocationCandidate

if TYPE_CHECKING:
    from globaltimezonebot.storage import Storage


def test_add_and_list_locations(storage: Storage, berlin_candidate) -> None:
    saved = storage.add_location(62056065, berlin_candidate)

    locations = storage.list_locations(62056065)

    assert [location.id for location in locations] == [saved.id]
    assert locations[0].label == "Berlin, Germany"


def test_set_home_location(storage: Storage, berlin_candidate) -> None:
    saved = storage.add_location(62056065, berlin_candidate)
    home = storage.set_home_location(62056065, saved.id)
    current_home = storage.get_home_location(62056065)

    assert home.id == saved.id
    assert current_home is not None
    assert current_home.id == saved.id


def test_remove_location_clears_home(storage: Storage, berlin_candidate) -> None:
    saved = storage.add_location(62056065, berlin_candidate)
    storage.set_home_location(62056065, saved.id)

    removed = storage.remove_location(62056065, saved.id)

    assert removed.id == saved.id
    assert storage.get_home_location(62056065) is None
    assert storage.list_locations(62056065) == []


def test_set_display_mode(storage: Storage) -> None:
    preferences = storage.set_display_mode(62056065, DisplayMode.TIMEZONE)

    assert preferences.display_mode is DisplayMode.TIMEZONE
    assert storage.get_preferences(62056065).display_mode is DisplayMode.TIMEZONE


def test_add_location_updates_existing_entry_for_same_coordinates(
    storage: Storage,
    berlin_candidate: LocationCandidate,
) -> None:
    storage.add_location(62056065, berlin_candidate)
    refreshed = LocationCandidate(
        place_name="Berlin",
        label="Berlin, Germany ✨",
        country_name="Germany",
        country_code="DE",
        latitude=52.52,
        longitude=13.405,
        timezone_name="Europe/Berlin",
    )

    updated = storage.add_location(62056065, refreshed)
    locations = storage.list_locations(62056065)

    assert len(locations) == 1
    assert updated.label == "Berlin, Germany ✨"
    assert locations[0].label == "Berlin, Germany ✨"
