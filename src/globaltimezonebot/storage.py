from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from globaltimezonebot.models import ChatPreferences, DisplayMode, SavedLocation

if TYPE_CHECKING:
    from pathlib import Path

    from globaltimezonebot.models import LocationCandidate


class Storage:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    display_mode TEXT NOT NULL DEFAULT 'place',
                    home_location_id INTEGER
                );

                CREATE TABLE IF NOT EXISTS saved_locations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    place_name TEXT NOT NULL,
                    label TEXT NOT NULL,
                    country_name TEXT NOT NULL,
                    country_code TEXT,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    timezone_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(chat_id, label, latitude, longitude, timezone_name)
                );
                """
            )
            connection.commit()
        self._cleanup_duplicate_locations()

    def ensure_chat(self, chat_id: int) -> ChatPreferences:
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO chats(chat_id) VALUES (?) ON CONFLICT(chat_id) DO NOTHING",
                (chat_id,),
            )
            connection.commit()
        return self._get_preferences(chat_id)

    def get_preferences(self, chat_id: int) -> ChatPreferences:
        self.ensure_chat(chat_id)
        return self._get_preferences(chat_id)

    def _get_preferences(self, chat_id: int) -> ChatPreferences:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT chat_id, display_mode, home_location_id FROM chats WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None:
            msg = f"Missing chat preferences for {chat_id}"
            raise LookupError(msg)
        return ChatPreferences(
            chat_id=int(row["chat_id"]),
            display_mode=DisplayMode(str(row["display_mode"])),
            home_location_id=int(row["home_location_id"]) if row["home_location_id"] else None,
        )

    def set_display_mode(self, chat_id: int, display_mode: DisplayMode) -> ChatPreferences:
        self.ensure_chat(chat_id)
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE chats SET display_mode = ? WHERE chat_id = ?",
                (display_mode.value, chat_id),
            )
            connection.commit()
        return self.get_preferences(chat_id)

    def add_location(self, chat_id: int, candidate: LocationCandidate) -> SavedLocation:
        self.ensure_chat(chat_id)
        created_at = datetime.now(tz=timezone.utc).isoformat()
        latitude = round(candidate.latitude, 6)
        longitude = round(candidate.longitude, 6)
        with closing(self._connect()) as connection:
            existing = connection.execute(
                """
                SELECT id
                FROM saved_locations
                WHERE chat_id = ?
                  AND timezone_name = ?
                  AND latitude BETWEEN ? AND ?
                  AND longitude BETWEEN ? AND ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    chat_id,
                    candidate.timezone_name,
                    latitude - 0.000001,
                    latitude + 0.000001,
                    longitude - 0.000001,
                    longitude + 0.000001,
                ),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE saved_locations
                    SET place_name = ?,
                        label = ?,
                        country_name = ?,
                        country_code = ?,
                        latitude = ?,
                        longitude = ?,
                        created_at = ?
                    WHERE id = ?
                    """,
                    (
                        candidate.place_name,
                        candidate.label,
                        candidate.country_name,
                        candidate.country_code,
                        latitude,
                        longitude,
                        created_at,
                        int(existing["id"]),
                    ),
                )
                location_id = int(existing["id"])
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO saved_locations(
                        chat_id,
                        place_name,
                        label,
                        country_name,
                        country_code,
                        latitude,
                        longitude,
                        timezone_name,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (
                        chat_id,
                        candidate.place_name,
                        candidate.label,
                        candidate.country_name,
                        candidate.country_code,
                        latitude,
                        longitude,
                        candidate.timezone_name,
                        created_at,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    msg = f"Failed to store location {candidate.label!r}"
                    raise RuntimeError(msg)
                location_id = int(row["id"])
            connection.commit()
        self._cleanup_duplicate_locations(chat_id=chat_id)
        return self.get_location(chat_id, location_id)

    def list_locations(self, chat_id: int) -> list[SavedLocation]:
        self.ensure_chat(chat_id)
        self._cleanup_duplicate_locations(chat_id=chat_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, chat_id, place_name, label, country_name, country_code,
                       latitude, longitude, timezone_name, created_at
                FROM saved_locations
                WHERE chat_id = ?
                ORDER BY label COLLATE NOCASE
                """,
                (chat_id,),
            ).fetchall()
        return [self._row_to_saved_location(row) for row in rows]

    def get_location(self, chat_id: int, location_id: int) -> SavedLocation:
        self.ensure_chat(chat_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, chat_id, place_name, label, country_name, country_code,
                       latitude, longitude, timezone_name, created_at
                FROM saved_locations
                WHERE chat_id = ? AND id = ?
                """,
                (chat_id, location_id),
            ).fetchone()
        if row is None:
            msg = f"Location {location_id} not found for chat {chat_id}"
            raise LookupError(msg)
        return self._row_to_saved_location(row)

    def set_home_location(self, chat_id: int, location_id: int) -> SavedLocation:
        location = self.get_location(chat_id, location_id)
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE chats SET home_location_id = ? WHERE chat_id = ?",
                (location.id, chat_id),
            )
            connection.commit()
        return location

    def set_home_candidate(self, chat_id: int, candidate: LocationCandidate) -> SavedLocation:
        saved = self.add_location(chat_id, candidate)
        return self.set_home_location(chat_id, saved.id)

    def get_home_location(self, chat_id: int) -> SavedLocation | None:
        preferences = self.get_preferences(chat_id)
        if preferences.home_location_id is None:
            return None
        try:
            return self.get_location(chat_id, preferences.home_location_id)
        except LookupError:
            with closing(self._connect()) as connection:
                connection.execute(
                    "UPDATE chats SET home_location_id = NULL WHERE chat_id = ?",
                    (chat_id,),
                )
                connection.commit()
            return None

    def remove_location(self, chat_id: int, location_id: int) -> SavedLocation:
        location = self.get_location(chat_id, location_id)
        with closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM saved_locations WHERE chat_id = ? AND id = ?",
                (chat_id, location_id),
            )
            connection.execute(
                (
                    "UPDATE chats SET home_location_id = NULL "
                    "WHERE chat_id = ? AND home_location_id = ?"
                ),
                (chat_id, location_id),
            )
            connection.commit()
        return location

    def _cleanup_duplicate_locations(self, chat_id: int | None = None) -> None:
        with closing(self._connect()) as connection:
            query = (
                "SELECT id, chat_id, latitude, longitude, timezone_name, created_at "
                "FROM saved_locations"
            )
            params: tuple[int, ...] = ()
            if chat_id is not None:
                query += " WHERE chat_id = ?"
                params = (chat_id,)
            query += " ORDER BY created_at DESC, id DESC"
            rows = connection.execute(query, params).fetchall()

            seen: dict[tuple[int, int, int, str], int] = {}
            removals: list[tuple[int, int]] = []
            for row in rows:
                key = (
                    int(row["chat_id"]),
                    round(float(row["latitude"]) * 1_000_000),
                    round(float(row["longitude"]) * 1_000_000),
                    str(row["timezone_name"]),
                )
                if key not in seen:
                    seen[key] = int(row["id"])
                    continue
                removals.append((int(row["id"]), seen[key]))

            for remove_id, keep_id in removals:
                connection.execute(
                    "UPDATE chats SET home_location_id = ? WHERE home_location_id = ?",
                    (keep_id, remove_id),
                )
                connection.execute(
                    "DELETE FROM saved_locations WHERE id = ?",
                    (remove_id,),
                )
            connection.commit()

    @staticmethod
    def _row_to_saved_location(row: sqlite3.Row) -> SavedLocation:
        return SavedLocation(
            id=int(row["id"]),
            chat_id=int(row["chat_id"]),
            place_name=str(row["place_name"]),
            label=str(row["label"]),
            country_name=str(row["country_name"]),
            country_code=str(row["country_code"]) if row["country_code"] else None,
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            timezone_name=str(row["timezone_name"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
        )
