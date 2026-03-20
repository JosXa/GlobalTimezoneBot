# globaltimezonebot

A revived Telegram bot for answering "what time is it there?" without depending on a remote timezone API.

## What changed

- modern `src/` package layout
- `python-telegram-bot` async application
- offline timezone lookup via `timezonefinder` + `zoneinfo`
- SQLite persistence for saved locations, home location, and display preferences
- `uv`, `ruff`, `ty`, `pytest`, `pre-commit`, and `mise` wired in

## Running

1. Create `.env` from `.env.example`
2. Review `commands.txt` — it is the source of truth for Telegram bot commands
3. Install dependencies with `uv sync`
4. Start the bot with `uv run globaltimezonebot`

On startup, the bot reads `commands.txt`, compares it with the live Telegram command list, and updates the bot commands only when they differ. If Telegram rate-limits that update, the bot logs it and moves on instead of blocking startup.

## Commands

- `/start` — welcome and quick actions
- `/help` — usage and examples
- `/now <place>` — current time for a location
- `/sun <place>` — sunrise, sunset, and daylight length
- `/add <place>` — save a location
- `/home <place>` — set your home location
- `/compare <place>` — compare a place against your home location
- `/compare Berlin | Tokyo` — direct two-place showdown
- `/meeting` — ephemeral picker for the places relevant to this meeting
- `/meeting Berlin | Tokyo | New York` — ad hoc meeting suggestions
- `/manage` — visual registry control for saved places
- `/overview` — playful world clockboard
- `/remove <name-or-number>` — remove a saved location
- `/display <place|country|timezone>` — choose how saved locations are shown

## UI direction

The useful shape for a timezone bot is not "show me everything", it's quick personal workflows:

- one-shot lookup from plain text or a dropped pin
- save/home/compare flows for recurring contacts and teams
- sunrise/sunset cards for travel and daylight awareness
- meeting-window suggestions across saved places or ad hoc place sets
- a playful overview sorted by local time and grouped by day
- inline results you can paste into other chats
- low-friction removal and display preferences when the list gets crowded

That is the direction implemented here. If you want to push it further, the next high-value UI additions would be named groups (e.g. "team", "family", "travel"), better disambiguation chips for cities with the same name, and richer compare output for meeting windows.

## Notes

Timezone resolution is fully local and deterministic. Geocoding still needs a networked place search service because otherwise users would have to send raw coordinates like animals.
