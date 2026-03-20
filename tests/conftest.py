from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from globaltimezonebot.models import LocationCandidate
from globaltimezonebot.storage import Storage

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "test.sqlite3")


@pytest.fixture()
def berlin_candidate() -> LocationCandidate:
    return LocationCandidate(
        place_name="Berlin",
        label="Berlin, Germany",
        country_name="Germany",
        country_code="DE",
        latitude=52.52,
        longitude=13.405,
        timezone_name="Europe/Berlin",
    )


@pytest.fixture()
def new_york_candidate() -> LocationCandidate:
    return LocationCandidate(
        place_name="New York",
        label="New York, United States",
        country_name="United States",
        country_code="US",
        latitude=40.7128,
        longitude=-74.006,
        timezone_name="America/New_York",
    )
