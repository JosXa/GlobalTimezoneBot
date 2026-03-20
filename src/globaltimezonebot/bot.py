from __future__ import annotations

import asyncio
import logging
import secrets
from collections import defaultdict
from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING, Any, Literal

from telegram import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from globaltimezonebot.config import PROJECT_ROOT
from globaltimezonebot.models import (
    DisplayMode,
    LocationCandidate,
    MeetingSuggestion,
    SavedLocation,
)
from globaltimezonebot.services import (
    GeocodingService,
    LocationLookupError,
    TimeService,
    as_candidate,
)
from globaltimezonebot.storage import Storage

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from globaltimezonebot.config import Settings

LOGGER = logging.getLogger(__name__)

MENU_LABELS = {
    "overview": "🌎 Overview",
    "meeting": "🤝 Meeting",
    "manage": "🧰 Manage",
    "display": "🎛 Display",
    "remove": "🗑 Remove",
    "help": "❓ Help",
}

MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [MENU_LABELS["overview"], MENU_LABELS["meeting"]],
        [MENU_LABELS["manage"], MENU_LABELS["display"]],
        [MENU_LABELS["remove"], MENU_LABELS["help"]],
    ],
    resize_keyboard=True,
)

ActionMode = Literal["preview", "add", "home", "compare_home"]


@dataclass(slots=True)
class PendingSelection:
    owner_chat_id: int
    mode: ActionMode
    candidates: list[LocationCandidate]


@dataclass(slots=True)
class PendingCandidateAction:
    owner_chat_id: int
    candidate: LocationCandidate


@dataclass(slots=True)
class MeetingSelectionSession:
    owner_chat_id: int
    ordered_location_ids: list[int]
    selected_location_ids: set[int]


class GlobalTimezoneBot:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage = Storage(settings.database_path)
        self.time_service = TimeService()
        self.geocoding = GeocodingService(
            user_agent=settings.geocoder_user_agent,
            time_service=self.time_service,
        )
        self._pending_selections: dict[str, PendingSelection] = {}
        self._pending_candidates: dict[str, PendingCandidateAction] = {}
        self._meeting_sessions: dict[str, MeetingSelectionSession] = {}
        self._chat_input_mode: dict[int, str] = {}
        self._command_sync_task: asyncio.Task[None] | None = None
        self.commands_path = PROJECT_ROOT / "commands.txt"

    def build_application(self) -> Application:
        builder = ApplicationBuilder().token(self.settings.bot_token)
        application = builder.post_init(self._post_init).build()
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("now", self.now_command))
        application.add_handler(CommandHandler("sun", self.sun_command))
        application.add_handler(CommandHandler("add", self.add_command))
        application.add_handler(CommandHandler("home", self.home_command))
        application.add_handler(CommandHandler("compare", self.compare_command))
        application.add_handler(CommandHandler("meeting", self.meeting_command))
        application.add_handler(CommandHandler("manage", self.manage_command))
        application.add_handler(CommandHandler("overview", self.overview_command))
        application.add_handler(CommandHandler("remove", self.remove_command))
        application.add_handler(CommandHandler("display", self.display_command))
        application.add_handler(InlineQueryHandler(self.inline_query))
        application.add_handler(CallbackQueryHandler(self.callback_router))
        application.add_handler(MessageHandler(filters.LOCATION, self.location_message))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_message))
        application.add_error_handler(self.error_handler)
        return application

    async def _post_init(self, application: Application) -> None:
        self._command_sync_task = asyncio.create_task(self._sync_commands_from_file(application))

    async def _sync_commands_from_file(self, application: Application) -> None:
        try:
            desired_commands = _load_commands_file(self.commands_path)
        except (OSError, ValueError) as exc:
            LOGGER.warning("Skipping command sync: %s", exc)
            return

        try:
            current_commands = await application.bot.get_my_commands()
        except TelegramError as exc:
            LOGGER.warning("Could not fetch bot commands: %s", exc)
            return

        if _commands_match(current_commands, desired_commands):
            LOGGER.info("Bot commands already up to date")
            return

        try:
            await application.bot.set_my_commands(desired_commands)
        except RetryAfter as exc:
            LOGGER.warning("Skipping command sync due to rate limit: %s", exc)
            return
        except TelegramError as exc:
            LOGGER.warning("Could not update bot commands: %s", exc)
            return

        LOGGER.info("Bot commands synchronized from commands.txt")

    async def error_handler(
        self,
        update: object,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        LOGGER.exception("Unhandled bot error", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message is not None:
            await update.effective_message.reply_text(
                "That went sideways. Try again in a second.",
                reply_markup=MENU_KEYBOARD,
            )

    async def start(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat_id = _chat_id(update)
        if message is None or chat_id is None:
            return
        self.storage.ensure_chat(chat_id)
        await message.reply_text(
            _start_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=MENU_KEYBOARD,
        )

    async def help_command(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return
        await message.reply_text(
            _help_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=MENU_KEYBOARD,
        )

    async def now_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._handle_query_command(update, context, mode="preview")

    async def add_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._handle_query_command(update, context, mode="add")

    async def home_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self._handle_query_command(update, context, mode="home")

    async def sun_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None:
            return
        query = _command_query(context)
        if not query:
            await message.reply_text(
                "Use /sun &lt;place&gt;. Example: /sun Reykjavik",
                parse_mode=ParseMode.HTML,
                reply_markup=MENU_KEYBOARD,
            )
            return
        candidate = await self._lookup_first_candidate(query)
        if candidate is None:
            await message.reply_text(
                f"I couldn't find a solid place for {escape(query)}.",
                parse_mode=ParseMode.HTML,
                reply_markup=MENU_KEYBOARD,
            )
            return
        await message.reply_text(
            self._render_sun_card(candidate),
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML,
            reply_markup=MENU_KEYBOARD,
        )

    async def compare_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat_id = _chat_id(update)
        if message is None or chat_id is None:
            return
        query = _command_query(context)
        if "|" in query:
            queries = [part.strip() for part in query.split("|") if part.strip()]
            if len(queries) != 2:
                await message.reply_text(
                    "Use /compare Berlin | Tokyo for a direct two-place showdown.",
                    reply_markup=MENU_KEYBOARD,
                )
                return
            left = await self._lookup_first_candidate(queries[0])
            right = await self._lookup_first_candidate(queries[1])
            if left is None or right is None:
                await message.reply_text(
                    "One of those places was too fuzzy. Try city plus country.",
                    reply_markup=MENU_KEYBOARD,
                )
                return
            await message.reply_text(
                self._render_pair_comparison(left, right),
                disable_web_page_preview=True,
                parse_mode=ParseMode.HTML,
                reply_markup=MENU_KEYBOARD,
            )
            return
        await self._handle_query_command(update, context, mode="compare_home")

    async def meeting_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat_id = _chat_id(update)
        if message is None or chat_id is None:
            return

        query = _command_query(context)
        if query:
            places: list[LocationCandidate] = []
            query_parts = [part.strip() for part in query.split("|") if part.strip()]
            for part in query_parts:
                candidate = await self._lookup_first_candidate(part)
                if candidate is None:
                    await message.reply_text(
                        f"I couldn't pin down {escape(part)}. Try city plus country.",
                        parse_mode=ParseMode.HTML,
                        reply_markup=MENU_KEYBOARD,
                    )
                    return
                places.append(candidate)
            if len(places) < 2:
                await message.reply_text(
                    "I need at least two places. Use more than one timezone, "
                    "you magnificent goblin.",
                    reply_markup=MENU_KEYBOARD,
                )
                return
            suggestions = self.time_service.meeting_suggestions(places)
            await message.reply_text(
                self._render_meeting_suggestions(places, suggestions),
                parse_mode=ParseMode.HTML,
                reply_markup=MENU_KEYBOARD,
            )
            return

        saved_locations = self.storage.list_locations(chat_id)
        if len(saved_locations) < 2:
            await message.reply_text(
                "I need at least two saved places before the picker makes sense. "
                "Use /add or pass places directly like /meeting Berlin | Tokyo.",
                reply_markup=MENU_KEYBOARD,
            )
            return

        token = self._create_meeting_session(chat_id, saved_locations)
        await message.reply_text(
            self._render_meeting_picker(saved_locations, self._meeting_sessions[token]),
            parse_mode=ParseMode.HTML,
            reply_markup=self._meeting_picker_markup(token, saved_locations),
        )

    async def manage_command(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat_id = _chat_id(update)
        if message is None or chat_id is None:
            return
        locations = self.storage.list_locations(chat_id)
        await message.reply_text(
            self._render_manage_dashboard(chat_id, locations),
            parse_mode=ParseMode.HTML,
            reply_markup=self._manage_dashboard_markup(locations),
        )

    async def overview_command(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat_id = _chat_id(update)
        if message is None or chat_id is None:
            return
        locations = self.storage.list_locations(chat_id)
        if not locations:
            await message.reply_text(
                "Your atlas is empty. Use /add &lt;place&gt; and let's fix that.",
                parse_mode=ParseMode.HTML,
                reply_markup=MENU_KEYBOARD,
            )
            return
        await message.reply_text(
            self._render_overview(chat_id, locations),
            parse_mode=ParseMode.HTML,
            reply_markup=MENU_KEYBOARD,
        )

    async def remove_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat_id = _chat_id(update)
        if message is None or chat_id is None:
            return
        locations = self.storage.list_locations(chat_id)
        if not locations:
            await message.reply_text(
                "Nothing to remove. Your saved list is empty.",
                reply_markup=MENU_KEYBOARD,
            )
            return

        query = _command_query(context)
        if query:
            location = self._find_saved_location(locations, query)
            if location is None:
                await message.reply_text(
                    "I couldn't match that saved place. Use /remove to see the numbered list.",
                    reply_markup=MENU_KEYBOARD,
                )
                return
            removed = self.storage.remove_location(chat_id, location.id)
            await message.reply_text(
                f"🗑 Poof. Removed <b>{escape(removed.label)}</b>.",
                parse_mode=ParseMode.HTML,
                reply_markup=MENU_KEYBOARD,
            )
            return

        keyboard = [
            [InlineKeyboardButton(f"✖ {location.label}", callback_data=f"remove:{location.id}")]
            for location in locations
        ]
        numbered = "\n".join(
            f"{index}. {escape(location.label)}"
            for index, location in enumerate(locations, start=1)
        )
        await message.reply_text(
            "<b>Choose a saved location to remove</b>\n"
            "You can also use <code>/remove 2</code> or <code>/remove Tokyo</code>.\n\n"
            f"{numbered}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def display_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat_id = _chat_id(update)
        if message is None or chat_id is None:
            return

        query = _command_query(context)
        if query:
            display_mode = _parse_display_mode(query)
            if display_mode is None:
                await message.reply_text(
                    "Use /display place, /display country, or /display timezone.",
                    reply_markup=MENU_KEYBOARD,
                )
                return
            self.storage.set_display_mode(chat_id, display_mode)
            await message.reply_text(
                f"🎛 Overview display is now <b>{escape(display_mode.label.lower())}</b>.",
                parse_mode=ParseMode.HTML,
                reply_markup=MENU_KEYBOARD,
            )
            return

        preferences = self.storage.get_preferences(chat_id)
        keyboard = [
            [
                InlineKeyboardButton(
                    text=f"{'✅ ' if mode is preferences.display_mode else ''}{mode.label}",
                    callback_data=f"display:{mode.value}",
                )
            ]
            for mode in DisplayMode
        ]
        await message.reply_text(
            "<b>How should the overview label places?</b>\n"
            "You can also use <code>/display timezone</code> directly.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def location_message(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat_id = _chat_id(update)
        if message is None or chat_id is None or message.location is None:
            return
        mode = self._chat_input_mode.pop(chat_id, None)
        try:
            candidates = await self.geocoding.reverse(
                latitude=message.location.latitude,
                longitude=message.location.longitude,
            )
        except LocationLookupError:
            await message.reply_text(
                "I couldn't resolve that pin into a useful place. Try a nearby city name instead.",
                reply_markup=MENU_KEYBOARD,
            )
            return
        await self._present_candidates(
            update=update,
            chat_id=chat_id,
            candidates=candidates,
            mode="add" if mode == "manage_add" else "preview",
            original_query="your pinned location",
        )

    async def text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        if message is None or message.text is None:
            return
        text = message.text.strip()
        mode = self._chat_input_mode.pop(message.chat_id, None)
        if mode == "manage_add" and text not in MENU_LABELS.values():
            await self._resolve_query(
                update,
                chat_id=message.chat_id,
                query=text,
                mode="add",
            )
            return
        if text == MENU_LABELS["overview"]:
            await self.overview_command(update, context)
            return
        if text == MENU_LABELS["meeting"]:
            await self.meeting_command(update, context)
            return
        if text == MENU_LABELS["manage"]:
            await self.manage_command(update, context)
            return
        if text == MENU_LABELS["display"]:
            await self.display_command(update, context)
            return
        if text == MENU_LABELS["remove"]:
            await self.remove_command(update, context)
            return
        if text == MENU_LABELS["help"]:
            await self.help_command(update, context)
            return
        await self._resolve_query(
            update,
            chat_id=message.chat_id,
            query=text,
            mode="preview",
        )

    async def inline_query(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        inline_query = update.inline_query
        if inline_query is None:
            return
        query = inline_query.query.strip()
        user_id = inline_query.from_user.id
        candidates: list[LocationCandidate] = []
        if query:
            try:
                candidates = await self.geocoding.search(query, limit=5)
            except LocationLookupError:
                candidates = []
        saved_candidates = [
            as_candidate(location) for location in self.storage.list_locations(user_id)
        ]
        articles = [
            self._inline_article(candidate, compare_chat_id=user_id) for candidate in candidates
        ]
        seen_labels = {candidate.label.casefold() for candidate in candidates}
        for candidate in saved_candidates:
            if candidate.label.casefold() in seen_labels:
                continue
            articles.append(self._inline_article(candidate, compare_chat_id=user_id))
        await inline_query.answer(articles[:20], cache_time=60, is_personal=True)

    async def callback_router(self, update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
        callback_query = update.callback_query
        chat_id = _chat_id(update)
        if callback_query is None or chat_id is None:
            return
        await callback_query.answer()
        data = callback_query.data or ""
        if data.startswith("pick:"):
            await self._handle_pick_callback(update, chat_id, data)
            return
        if data.startswith("save:"):
            await self._handle_save_callback(update, chat_id, data)
            return
        if data.startswith("homecandidate:"):
            await self._handle_home_candidate_callback(update, chat_id, data)
            return
        if data.startswith("remove:"):
            await self._handle_remove_callback(update, chat_id, data)
            return
        if data.startswith("display:"):
            await self._handle_display_callback(update, chat_id, data)
            return
        if data.startswith("meetingtoggle:"):
            await self._handle_meeting_toggle_callback(update, chat_id, data)
            return
        if data.startswith("meetingall:"):
            await self._handle_meeting_all_callback(update, chat_id, data)
            return
        if data.startswith("meetingclear:"):
            await self._handle_meeting_clear_callback(update, chat_id, data)
            return
        if data.startswith("meetingrun:"):
            await self._handle_meeting_run_callback(update, chat_id, data)
            return
        if data.startswith("meetingcancel:"):
            await self._handle_meeting_cancel_callback(update, chat_id, data)
            return
        if data.startswith("manage:"):
            await self._handle_manage_callback(update, chat_id, data)

    async def _handle_query_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        mode: ActionMode,
    ) -> None:
        message = update.effective_message
        chat_id = _chat_id(update)
        if message is None or chat_id is None:
            return
        query = _command_query(context)
        if not query:
            prompt = {
                "preview": "Use /now &lt;place&gt;. Example: /now Nairobi",
                "add": "Use /add &lt;place&gt;. Example: /add Reykjavik",
                "home": "Use /home &lt;place&gt;. Example: /home Berlin",
                "compare_home": "Use /compare &lt;place&gt; or /compare Berlin | Tokyo",
            }[mode]
            await message.reply_text(
                prompt,
                parse_mode=ParseMode.HTML,
                reply_markup=MENU_KEYBOARD,
            )
            return
        await self._resolve_query(update, chat_id=chat_id, query=query, mode=mode)

    async def _resolve_query(
        self,
        update: Update,
        *,
        chat_id: int,
        query: str,
        mode: ActionMode,
    ) -> None:
        message = update.effective_message
        if message is None:
            return
        try:
            candidates = await self.geocoding.search(query)
        except LocationLookupError:
            await message.reply_text(
                "The place lookup failed. That's the geocoder having a moment, not you.",
                reply_markup=MENU_KEYBOARD,
            )
            return
        await self._present_candidates(
            update=update,
            chat_id=chat_id,
            candidates=candidates,
            mode=mode,
            original_query=query,
        )

    async def _present_candidates(
        self,
        *,
        update: Update,
        chat_id: int,
        candidates: list[LocationCandidate],
        mode: ActionMode,
        original_query: str,
    ) -> None:
        message = update.effective_message
        if message is None:
            return
        if not candidates:
            await message.reply_text(
                f"I couldn't find a place for {escape(original_query)!s}. Try a city plus country.",
                parse_mode=ParseMode.HTML,
                reply_markup=MENU_KEYBOARD,
            )
            return
        if len(candidates) == 1:
            await self._finish_candidate_mode(update, chat_id, mode, candidates[0])
            return
        token = self._remember_selection(chat_id, mode, candidates)
        keyboard = [
            [InlineKeyboardButton(candidate.label, callback_data=f"pick:{token}:{index}")]
            for index, candidate in enumerate(candidates[:5])
        ]
        await message.reply_text(
            "I found a few matches. Pick the best one:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    async def _finish_candidate_mode(
        self,
        update: Update,
        chat_id: int,
        mode: ActionMode,
        candidate: LocationCandidate,
    ) -> None:
        rendered = self._render_location(candidate, compare_chat_id=chat_id)
        if mode == "add":
            saved = self.storage.add_location(chat_id, candidate)
            await self._present_result_text(
                callback_query=update.callback_query,
                message=update.effective_message,
                text=f"✨ Saved <b>{escape(saved.label)}</b>.\n\n{rendered}",
                inline_reply_markup=None,
            )
            return
        if mode == "home":
            saved = self.storage.set_home_candidate(chat_id, candidate)
            await self._present_result_text(
                callback_query=update.callback_query,
                message=update.effective_message,
                text=f"🏠 Home is now <b>{escape(saved.label)}</b>.\n\n{rendered}",
                inline_reply_markup=None,
            )
            return
        if mode == "compare_home":
            home = self.storage.get_home_location(chat_id)
            if home is None:
                await self._present_result_text(
                    callback_query=update.callback_query,
                    message=update.effective_message,
                    text="Set a home location first with /home &lt;place&gt;, then compare away.",
                    disable_web_page_preview=False,
                    inline_reply_markup=None,
                )
                return
            await self._present_result_text(
                callback_query=update.callback_query,
                message=update.effective_message,
                text=rendered,
                inline_reply_markup=None,
            )
            return
        await self._present_result_text(
            callback_query=update.callback_query,
            message=update.effective_message,
            text=self._render_location(candidate, compare_chat_id=chat_id, include_actions=True),
            inline_reply_markup=self._candidate_action_markup(chat_id, candidate),
        )

    async def _handle_pick_callback(self, update: Update, chat_id: int, data: str) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        _, token, raw_index = data.split(":", 2)
        selection = self._pending_selections.get(token)
        if selection is None or selection.owner_chat_id != chat_id:
            await callback_query.edit_message_text("That selection expired. Run the command again.")
            return
        try:
            candidate = selection.candidates[int(raw_index)]
        except (IndexError, ValueError):
            await callback_query.edit_message_text("That selection went stale. Try again.")
            return
        del self._pending_selections[token]
        await self._finish_candidate_mode(update, chat_id, selection.mode, candidate)

    async def _handle_save_callback(self, update: Update, chat_id: int, data: str) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        token = data.removeprefix("save:")
        pending = self._pending_candidates.get(token)
        if pending is None or pending.owner_chat_id != chat_id:
            await callback_query.edit_message_text("That save action expired. Ask me again.")
            return
        saved = self.storage.add_location(chat_id, pending.candidate)
        rendered = self._render_location(pending.candidate, compare_chat_id=chat_id)
        await callback_query.edit_message_text(
            f"✨ Saved <b>{escape(saved.label)}</b>.\n\n{rendered}",
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML,
        )
        del self._pending_candidates[token]

    async def _handle_home_candidate_callback(
        self,
        update: Update,
        chat_id: int,
        data: str,
    ) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        token = data.removeprefix("homecandidate:")
        pending = self._pending_candidates.get(token)
        if pending is None or pending.owner_chat_id != chat_id:
            await callback_query.edit_message_text("That home action expired. Ask me again.")
            return
        saved = self.storage.set_home_candidate(chat_id, pending.candidate)
        rendered = self._render_location(pending.candidate, compare_chat_id=chat_id)
        await callback_query.edit_message_text(
            f"🏠 Home is now <b>{escape(saved.label)}</b>.\n\n{rendered}",
            disable_web_page_preview=True,
            parse_mode=ParseMode.HTML,
        )
        del self._pending_candidates[token]

    async def _handle_remove_callback(self, update: Update, chat_id: int, data: str) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        try:
            location_id = int(data.removeprefix("remove:"))
        except ValueError:
            await callback_query.edit_message_text("That remove action looked cursed. Try again.")
            return
        try:
            removed = self.storage.remove_location(chat_id, location_id)
        except LookupError:
            await callback_query.edit_message_text("That location was already gone.")
            return
        await callback_query.edit_message_text(f"🗑 Removed {removed.label}.")

    async def _handle_display_callback(self, update: Update, chat_id: int, data: str) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        raw_mode = data.removeprefix("display:")
        try:
            display_mode = DisplayMode(raw_mode)
        except ValueError:
            await callback_query.edit_message_text("Unknown display mode. Lovely.")
            return
        self.storage.set_display_mode(chat_id, display_mode)
        await callback_query.edit_message_text(
            f"🎛 Overview display is now {display_mode.label.lower()}."
        )

    async def _handle_manage_callback(self, update: Update, chat_id: int, data: str) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        parts = data.split(":", 2)
        if len(parts) < 2:
            await callback_query.edit_message_text(
                "That registry action was malformed. Try /manage again."
            )
            return
        action = parts[1]
        locations = self.storage.list_locations(chat_id)
        if action == "refresh":
            await callback_query.edit_message_text(
                self._render_manage_dashboard(chat_id, locations),
                parse_mode=ParseMode.HTML,
                reply_markup=self._manage_dashboard_markup(locations),
            )
            return
        if action == "add":
            self._chat_input_mode[chat_id] = "manage_add"
            await callback_query.edit_message_text(
                "✨ <b>Add mode armed</b>\n"
                "Send me the next city name or drop a location pin and I'll add it.\n\n"
                "When you're done, use /manage or tap the back button here next time.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back to registry", callback_data="manage:refresh")]]
                ),
            )
            return
        if action == "view" and len(parts) == 3:
            try:
                location_id = int(parts[2])
                location = self.storage.get_location(chat_id, location_id)
            except (LookupError, ValueError):
                await callback_query.edit_message_text(
                    "That location wandered off. Try /manage again."
                )
                return
            await callback_query.edit_message_text(
                self._render_manage_detail(chat_id, location),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=self._manage_detail_markup(location),
            )
            return
        if action == "home" and len(parts) == 3:
            try:
                location_id = int(parts[2])
                location = self.storage.set_home_location(chat_id, location_id)
            except (LookupError, ValueError):
                await callback_query.edit_message_text(
                    "That location wandered off. Try /manage again."
                )
                return
            await callback_query.edit_message_text(
                "🏠 <b>Home updated</b>\n\n" + self._render_manage_detail(chat_id, location),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=self._manage_detail_markup(location),
            )
            return
        if action == "remove" and len(parts) == 3:
            try:
                location_id = int(parts[2])
                removed = self.storage.remove_location(chat_id, location_id)
            except (LookupError, ValueError):
                await callback_query.edit_message_text(
                    "That location was already gone. Try /manage again."
                )
                return
            refreshed = self.storage.list_locations(chat_id)
            await callback_query.edit_message_text(
                f"🗑 <b>Removed {escape(removed.label)}</b>.\n\n"
                + self._render_manage_dashboard(chat_id, refreshed),
                parse_mode=ParseMode.HTML,
                reply_markup=self._manage_dashboard_markup(refreshed),
            )
            return
        await callback_query.edit_message_text(
            "That registry action was not recognized. Try /manage again."
        )

    async def _handle_meeting_toggle_callback(
        self,
        update: Update,
        chat_id: int,
        data: str,
    ) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        _, token, raw_location_id = data.split(":", 2)
        session = self._meeting_sessions.get(token)
        if session is None or session.owner_chat_id != chat_id:
            await callback_query.edit_message_text(
                "That meeting picker expired. Start /meeting again."
            )
            return
        try:
            location_id = int(raw_location_id)
        except ValueError:
            await callback_query.edit_message_text("That toggle looked cursed. Try /meeting again.")
            return
        if location_id in session.selected_location_ids:
            session.selected_location_ids.remove(location_id)
        elif location_id in session.ordered_location_ids:
            session.selected_location_ids.add(location_id)
        await self._refresh_meeting_picker(callback_query, token, chat_id)

    async def _handle_meeting_all_callback(
        self,
        update: Update,
        chat_id: int,
        data: str,
    ) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        token = data.removeprefix("meetingall:")
        session = self._meeting_sessions.get(token)
        if session is None or session.owner_chat_id != chat_id:
            await callback_query.edit_message_text(
                "That meeting picker expired. Start /meeting again."
            )
            return
        session.selected_location_ids = set(session.ordered_location_ids)
        await self._refresh_meeting_picker(callback_query, token, chat_id)

    async def _handle_meeting_clear_callback(
        self,
        update: Update,
        chat_id: int,
        data: str,
    ) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        token = data.removeprefix("meetingclear:")
        session = self._meeting_sessions.get(token)
        if session is None or session.owner_chat_id != chat_id:
            await callback_query.edit_message_text(
                "That meeting picker expired. Start /meeting again."
            )
            return
        session.selected_location_ids.clear()
        await self._refresh_meeting_picker(callback_query, token, chat_id)

    async def _handle_meeting_run_callback(
        self,
        update: Update,
        chat_id: int,
        data: str,
    ) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        token = data.removeprefix("meetingrun:")
        session = self._meeting_sessions.get(token)
        if session is None or session.owner_chat_id != chat_id:
            await callback_query.edit_message_text(
                "That meeting picker expired. Start /meeting again."
            )
            return
        selected_locations = self._selected_meeting_locations(chat_id, session)
        if len(selected_locations) < 2:
            await self._refresh_meeting_picker(
                callback_query,
                token,
                chat_id,
                status="Pick at least two places before I do meeting wizardry.",
            )
            return
        places = [as_candidate(location) for location in selected_locations]
        suggestions = self.time_service.meeting_suggestions(places)
        del self._meeting_sessions[token]
        await callback_query.edit_message_text(
            self._render_meeting_suggestions(places, suggestions),
            parse_mode=ParseMode.HTML,
        )

    async def _handle_meeting_cancel_callback(
        self,
        update: Update,
        chat_id: int,
        data: str,
    ) -> None:
        callback_query = update.callback_query
        if callback_query is None:
            return
        token = data.removeprefix("meetingcancel:")
        session = self._meeting_sessions.get(token)
        if session is None or session.owner_chat_id != chat_id:
            await callback_query.edit_message_text("That meeting picker was already gone.")
            return
        del self._meeting_sessions[token]
        await callback_query.edit_message_text(
            "🤝 Picker closed. Your global watchlist survives another day.",
        )

    async def _refresh_meeting_picker(
        self,
        callback_query: CallbackQuery,
        token: str,
        chat_id: int,
        *,
        status: str | None = None,
    ) -> None:
        session = self._meeting_sessions.get(token)
        if session is None:
            await callback_query.edit_message_text(
                "That meeting picker expired. Start /meeting again."
            )
            return
        locations = self.storage.list_locations(chat_id)
        if len(locations) < 2:
            del self._meeting_sessions[token]
            await callback_query.edit_message_text(
                "You don't have enough saved places anymore. Add a few and try /meeting again."
            )
            return
        text = self._render_meeting_picker(locations, session, status=status)
        markup = self._meeting_picker_markup(token, locations)
        await callback_query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )

    async def _present_result_text(
        self,
        *,
        callback_query: Any,
        message: Any,
        text: str,
        disable_web_page_preview: bool = True,
        inline_reply_markup: InlineKeyboardMarkup | None,
    ) -> None:
        if callback_query is not None:
            await callback_query.edit_message_text(
                text,
                disable_web_page_preview=disable_web_page_preview,
                parse_mode=ParseMode.HTML,
                reply_markup=inline_reply_markup,
            )
            return
        if message is None:
            return
        await message.reply_text(
            text,
            disable_web_page_preview=disable_web_page_preview,
            parse_mode=ParseMode.HTML,
            reply_markup=MENU_KEYBOARD,
        )

    async def _lookup_first_candidate(self, query: str) -> LocationCandidate | None:
        try:
            candidates = await self.geocoding.search(query, limit=1)
        except LocationLookupError:
            return None
        if not candidates:
            return None
        return candidates[0]

    def _find_saved_location(
        self,
        locations: list[SavedLocation],
        query: str,
    ) -> SavedLocation | None:
        normalized = query.strip().casefold()
        if normalized.isdigit():
            index = int(normalized) - 1
            if 0 <= index < len(locations):
                return locations[index]
            return None

        exact_matches = [
            location
            for location in locations
            if location.label.casefold() == normalized
            or location.place_name.casefold() == normalized
        ]
        if len(exact_matches) == 1:
            return exact_matches[0]

        partial_matches = [
            location
            for location in locations
            if normalized in location.label.casefold()
            or normalized in location.place_name.casefold()
            or normalized in location.country_name.casefold()
        ]
        if len(partial_matches) == 1:
            return partial_matches[0]
        return None

    def _create_meeting_session(
        self,
        chat_id: int,
        locations: list[SavedLocation],
    ) -> str:
        token = secrets.token_hex(4)
        self._meeting_sessions[token] = MeetingSelectionSession(
            owner_chat_id=chat_id,
            ordered_location_ids=[location.id for location in locations],
            selected_location_ids=set(),
        )
        return token

    def _selected_meeting_locations(
        self,
        chat_id: int,
        session: MeetingSelectionSession,
    ) -> list[SavedLocation]:
        available = {location.id: location for location in self.storage.list_locations(chat_id)}
        locations: list[SavedLocation] = []
        for location_id in session.ordered_location_ids:
            if location_id not in session.selected_location_ids:
                continue
            location = available.get(location_id)
            if location is not None:
                locations.append(location)
        return locations

    def _meeting_picker_markup(
        self,
        token: str,
        locations: list[SavedLocation],
    ) -> InlineKeyboardMarkup:
        session = self._meeting_sessions[token]
        buttons = []
        for location in locations:
            label = _meeting_button_label(location, location.id in session.selected_location_ids)
            buttons.append(
                [
                    InlineKeyboardButton(
                        label,
                        callback_data=f"meetingtoggle:{token}:{location.id}",
                    )
                ]
            )
        buttons.append(
            [
                InlineKeyboardButton("✨ Select all", callback_data=f"meetingall:{token}"),
                InlineKeyboardButton("🧹 Clear", callback_data=f"meetingclear:{token}"),
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton("🤝 Find meeting magic", callback_data=f"meetingrun:{token}"),
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton("✖ Close", callback_data=f"meetingcancel:{token}"),
            ]
        )
        return InlineKeyboardMarkup(buttons)

    def _render_meeting_picker(
        self,
        locations: list[SavedLocation],
        session: MeetingSelectionSession,
        *,
        status: str | None = None,
    ) -> str:
        selected_count = len(session.selected_location_ids)
        roster = []
        for location in locations:
            flag = _flag_emoji(location.country_code)
            marker = "✅" if location.id in session.selected_location_ids else "⬜"
            roster.append(f"{marker} {flag} {escape(location.place_name)}")
        status_line = ""
        if status is not None:
            status_line = f"\n<b>{escape(status)}</b>\n"
        return (
            "🤝 <b>Meeting picker</b>\n"
            "Your watchlist is broader than any one meeting. "
            "Pick only the places that matter right now.\n\n"
            f"Selected: <b>{selected_count}/{len(locations)}</b>{status_line}\n"
            "Tap places to toggle them, then hit <i>Find meeting magic</i>.\n\n" + "\n".join(roster)
        )

    def _manage_dashboard_markup(self, locations: list[SavedLocation]) -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton(
                    _manage_location_button_label(location),
                    callback_data=f"manage:view:{location.id}",
                )
            ]
            for location in locations
        ]
        buttons.append([InlineKeyboardButton("✨ Add place", callback_data="manage:add")])
        return InlineKeyboardMarkup(buttons)

    def _manage_detail_markup(self, location: SavedLocation) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🏠 Make home", callback_data=f"manage:home:{location.id}"
                    ),
                    InlineKeyboardButton("🗑 Remove", callback_data=f"manage:remove:{location.id}"),
                ],
                [InlineKeyboardButton("🔙 Back to registry", callback_data="manage:refresh")],
            ]
        )

    def _render_manage_dashboard(self, chat_id: int, locations: list[SavedLocation]) -> str:
        home = self.storage.get_home_location(chat_id)
        if not locations:
            return (
                "🧰 <b>Timezone registry</b>\n\n"
                "Nothing saved yet. Tap <i>Add place</i> below or use "
                "<code>/add &lt;place&gt;</code>."
            )
        home_text = "none yet"
        if home is not None:
            home_text = escape(home.label)
        lines = []
        for index, location in enumerate(locations, start=1):
            flag = _flag_emoji(location.country_code)
            home_marker = " 🏠" if home and home.id == location.id else ""
            lines.append(
                f"{index}. {escape((flag + ' ' + location.label).strip())}"
                f" · <code>{escape(location.timezone_name)}</code>{home_marker}"
            )
        return (
            "🧰 <b>Timezone registry</b>\n"
            f"Home: <b>{home_text}</b>\n"
            f"Saved places: <b>{len(locations)}</b>\n\n"
            "Tap a place below to inspect it, set it as home, or remove it.\n\n" + "\n".join(lines)
        )

    def _render_manage_detail(self, chat_id: int, location: SavedLocation) -> str:
        home = self.storage.get_home_location(chat_id)
        rendered = self._render_location(as_candidate(location), compare_chat_id=chat_id)
        home_status = "yes" if home and home.id == location.id else "no"
        return f"🧰 <b>Registry detail</b>\nHome location: <b>{home_status}</b>\n\n{rendered}"

    def _candidate_action_markup(
        self,
        chat_id: int,
        candidate: LocationCandidate,
    ) -> InlineKeyboardMarkup:
        save_token = self._remember_candidate(chat_id, candidate)
        home_token = self._remember_candidate(chat_id, candidate)
        keyboard = [
            [
                InlineKeyboardButton("✨ Save", callback_data=f"save:{save_token}"),
                InlineKeyboardButton("🏠 Set home", callback_data=f"homecandidate:{home_token}"),
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    def _inline_article(
        self,
        candidate: LocationCandidate,
        *,
        compare_chat_id: int,
    ) -> InlineQueryResultArticle:
        snapshot = self.time_service.snapshot(candidate.timezone_name)
        sky = self.time_service.sky_emoji(
            candidate.latitude,
            candidate.longitude,
            candidate.timezone_name,
        )
        text = self._render_location(candidate, compare_chat_id=compare_chat_id)
        return InlineQueryResultArticle(
            id=(f"{candidate.timezone_name}:{candidate.latitude:.3f}:{candidate.longitude:.3f}"),
            title=f"{sky} {candidate.place_name} · {snapshot.current_time.strftime('%H:%M')}",
            description=f"{candidate.label} · {candidate.timezone_name}",
            input_message_content=InputTextMessageContent(text, parse_mode=ParseMode.HTML),
        )

    def _render_overview(self, chat_id: int, locations: list[SavedLocation]) -> str:
        preferences = self.storage.get_preferences(chat_id)
        home = self.storage.get_home_location(chat_id)
        grouped_rows: dict[str, list[str]] = defaultdict(list)

        sortable_rows: list[tuple[datetime, str, str]] = []
        for location in locations:
            snapshot = self.time_service.snapshot(location.timezone_name)
            sky = self.time_service.sky_emoji(
                location.latitude,
                location.longitude,
                location.timezone_name,
            )
            label = self._overview_label(location, preferences.display_mode)
            diff_label = self._overview_difference(home, location)
            row = self._overview_row(location, snapshot.current_time, sky, label, diff_label)
            day_label = snapshot.current_time.strftime("%A").upper()
            sortable_rows.append((snapshot.current_time, day_label, row))

        sortable_rows.sort(key=lambda item: (item[0].date(), item[0].time(), item[2].casefold()))
        for _, day_label, row in sortable_rows:
            grouped_rows[day_label].append(row)

        sections = []
        for day_label, rows in grouped_rows.items():
            divider = f"━━ {day_label} {'━' * max(0, 26 - len(day_label))}"
            section = "\n".join([divider, *rows])
            sections.append(section)

        board = "\n\n".join(sections)
        return (
            "🌎🌍🌏 <b>Around your world</b> 🌏🌍🌎\n"
            "<i>Sky · local time · place · difference from home</i>\n\n"
            f"<pre>{escape(board)}</pre>"
        )

    @staticmethod
    def _overview_label(location: SavedLocation, display_mode: DisplayMode) -> str:
        if display_mode is DisplayMode.COUNTRY:
            return location.country_name
        if display_mode is DisplayMode.TIMEZONE:
            return location.timezone_name
        return location.label

    def _overview_difference(
        self,
        home: SavedLocation | None,
        location: SavedLocation,
    ) -> str:
        if home is None:
            return location.timezone_name
        if home.id == location.id:
            return "home"
        difference = self.time_service.offset_difference(home.timezone_name, location.timezone_name)
        total_minutes = int(difference.total_seconds() // 60)
        sign = "+" if total_minutes >= 0 else "-"
        hours, minutes = divmod(abs(total_minutes), 60)
        if minutes == 0:
            return f"{sign}{hours}h"
        return f"{sign}{hours}h{minutes:02d}"

    def _overview_row(
        self,
        location: SavedLocation,
        current_time: datetime,
        sky: str,
        label: str,
        diff_label: str,
    ) -> str:
        flag = _flag_emoji(location.country_code)
        compact_label = _clip(f"{flag} {label}".strip(), 26)
        return f"{sky:<2}  {current_time.strftime('%H:%M')}  {compact_label:<26}  {diff_label}"

    def _render_location(
        self,
        candidate: LocationCandidate,
        *,
        compare_chat_id: int,
        include_actions: bool = False,
    ) -> str:
        snapshot = self.time_service.snapshot(candidate.timezone_name)
        summary = self.time_service.sun_summary(
            candidate.latitude,
            candidate.longitude,
            candidate.timezone_name,
        )
        sky = self.time_service.sky_emoji(
            candidate.latitude,
            candidate.longitude,
            candidate.timezone_name,
        )
        flag = _flag_emoji(candidate.country_code)
        lines = [
            f"{sky} <b>{escape((flag + ' ' + candidate.label).strip())}</b>",
            f"🕒 {snapshot.current_time.strftime('%A, %Y-%m-%d %H:%M')}",
            f"🌐 {candidate.timezone_name} · {snapshot.offset_label}",
        ]
        if (
            summary.sunrise is not None
            and summary.sunset is not None
            and summary.daylight is not None
        ):
            lines.append(
                "🌅 "
                f"{summary.sunrise.strftime('%H:%M')} · 🌆 {summary.sunset.strftime('%H:%M')}"
                f" · ☀️ {summary.daylight.seconds // 3600}h"
                f" {(summary.daylight.seconds % 3600) // 60:02d}m"
            )
        lines.append(
            f"🧭 {candidate.latitude:.4f}, {candidate.longitude:.4f} · "
            f'<a href="{_map_url(candidate)}">OpenStreetMap</a>'
        )
        home = self.storage.get_home_location(compare_chat_id)
        if home is not None:
            difference = self.time_service.offset_difference(
                home.timezone_name,
                candidate.timezone_name,
            )
            difference_label = self.time_service.offset_difference_label(difference)
            home_name = escape(home.place_name)
            lines.append(f"⚖ Compared with home ({home_name}): {difference_label}")
        if include_actions:
            lines.append("\nTap below to save this place or crown it as home.")
        return "\n".join(lines)

    def _render_sun_card(self, candidate: LocationCandidate) -> str:
        snapshot = self.time_service.snapshot(candidate.timezone_name)
        summary = self.time_service.sun_summary(
            candidate.latitude,
            candidate.longitude,
            candidate.timezone_name,
        )
        sky = self.time_service.sky_emoji(
            candidate.latitude,
            candidate.longitude,
            candidate.timezone_name,
        )
        flag = _flag_emoji(candidate.country_code)
        lines = [
            f"{sky} <b>{escape((flag + ' ' + candidate.label).strip())}</b>",
            f"🗓 {snapshot.current_time.strftime('%A, %Y-%m-%d')}",
            f"🕒 Local time {snapshot.current_time.strftime('%H:%M')} · {snapshot.offset_label}",
        ]
        if summary.sunrise is None or summary.sunset is None or summary.daylight is None:
            lines.append("🌌 Sun data gets weird here today. Polar drama, basically.")
        else:
            daylight = summary.daylight.seconds
            lines.append(f"🌅 Sunrise {summary.sunrise.strftime('%H:%M')}")
            lines.append(f"🌆 Sunset  {summary.sunset.strftime('%H:%M')}")
            lines.append(f"☀️ Daylight {daylight // 3600}h {(daylight % 3600) // 60:02d}m")
        lines.append(f'🗺️ <a href="{_map_url(candidate)}">OpenStreetMap</a>')
        return "\n".join(lines)

    def _render_pair_comparison(
        self,
        left: LocationCandidate,
        right: LocationCandidate,
    ) -> str:
        left_snapshot = self.time_service.snapshot(left.timezone_name)
        right_snapshot = self.time_service.snapshot(right.timezone_name)
        difference = self.time_service.offset_difference(left.timezone_name, right.timezone_name)
        diff_label = self.time_service.offset_difference_label(difference)
        left_flag = _flag_emoji(left.country_code)
        right_flag = _flag_emoji(right.country_code)
        left_line = (
            f"• {left_snapshot.current_time.strftime('%A %H:%M')} · {left_snapshot.offset_label}"
        )
        right_line = (
            f"• {right_snapshot.current_time.strftime('%A %H:%M')} · {right_snapshot.offset_label}"
        )
        return (
            "⚖️ <b>Two-place showdown</b>\n\n"
            f"{escape((left_flag + ' ' + left.label).strip())}\n"
            f"{left_line}\n\n"
            f"{escape((right_flag + ' ' + right.label).strip())}\n"
            f"{right_line}\n\n"
            f"Result: <b>{escape(right.place_name)}</b> is <b>{escape(diff_label)}</b> "
            f"relative to <b>{escape(left.place_name)}</b>."
        )

    def _render_meeting_suggestions(
        self,
        places: list[LocationCandidate],
        suggestions: list[MeetingSuggestion],
    ) -> str:
        if not suggestions:
            return "🤝 I need at least two places before I can do meeting magic."

        roster = ", ".join(escape(place.place_name) for place in places)
        lines = [
            "🤝 <b>Meeting Magic</b>",
            f"<i>Least-cursed overlap for {len(places)} places: {roster}</i>",
            "",
        ]
        medals = ["🥇", "🥈", "🥉"]
        for medal, suggestion in zip(medals, suggestions, strict=False):
            lines.append(f"{medal} <b>{suggestion.utc_time.strftime('%a %H:%M UTC')}</b>")
            participant_lines = []
            for participant in suggestion.participants:
                flag = _flag_emoji(participant.country_code)
                participant_lines.append(
                    f"{flag} {participant.label:<12} {participant.local_time.strftime('%a %H:%M')}"
                )
            lines.append(f"<pre>{escape(chr(10).join(participant_lines))}</pre>")
        lines.append(
            "<i>Scored across the next 24 hours with a bias toward civilized daylight hours.</i>"
        )
        return "\n".join(lines)

    def _remember_selection(
        self,
        chat_id: int,
        mode: ActionMode,
        candidates: list[LocationCandidate],
    ) -> str:
        token = secrets.token_hex(4)
        self._pending_selections[token] = PendingSelection(chat_id, mode, candidates)
        return token

    def _remember_candidate(self, chat_id: int, candidate: LocationCandidate) -> str:
        token = secrets.token_hex(4)
        self._pending_candidates[token] = PendingCandidateAction(chat_id, candidate)
        return token


def _chat_id(update: Update) -> int | None:
    if update.effective_chat is None:
        return None
    return update.effective_chat.id


def _command_query(context: ContextTypes.DEFAULT_TYPE) -> str:
    raw_args = context.args
    args = raw_args if isinstance(raw_args, list) else []
    return " ".join(args).strip()


def _parse_display_mode(text: str) -> DisplayMode | None:
    normalized = text.strip().casefold()
    for mode in DisplayMode:
        if normalized == mode.value or normalized == mode.label.casefold():
            return mode
    return None


def _load_commands_file(path: Path) -> list[BotCommand]:
    lines = path.read_text(encoding="utf-8").splitlines()
    commands: list[BotCommand] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if " - " not in line:
            msg = f"commands.txt line {line_number} must look like 'command - description'"
            raise ValueError(msg)
        command, description = line.split(" - ", 1)
        command = command.strip().removeprefix("/")
        description = description.strip()
        if not command or not description:
            msg = f"commands.txt line {line_number} is incomplete"
            raise ValueError(msg)
        commands.append(BotCommand(command=command, description=description))
    if not commands:
        msg = f"No commands found in {path}"
        raise ValueError(msg)
    return commands


def _commands_match(current: list[BotCommand], desired: list[BotCommand]) -> bool:
    current_pairs = [(command.command, command.description) for command in current]
    desired_pairs = [(command.command, command.description) for command in desired]
    return current_pairs == desired_pairs


def _meeting_button_label(location: SavedLocation, selected: bool) -> str:
    marker = "✅" if selected else "⬜"
    flag = _flag_emoji(location.country_code)
    label = _clip(location.place_name, 18)
    return f"{marker} {flag} {label}".strip()


def _manage_location_button_label(location: SavedLocation) -> str:
    flag = _flag_emoji(location.country_code)
    label = _clip(location.place_name, 18)
    return f"{flag} {label}".strip()


def _start_text() -> str:
    return (
        "🌎🌍🌏 <b>GlobalTimezoneBot is alive again</b> 🌏🌍🌎\n\n"
        "A playful little clockboard for friends, teams, travel plans, and the eternal question: "
        "<i>what time is it over there?</i>\n\n"
        "Try one of these:\n"
        "• <code>/now Tokyo</code>\n"
        "• <code>/sun Reykjavik</code>\n"
        "• <code>/add São Paulo</code>\n"
        "• <code>/home Berlin</code>\n"
        "• <code>/compare Berlin | Tokyo</code>\n"
        "• <code>/meeting</code> for the picker\n"
        "• <code>/manage</code> for registry control\n"
        "• <code>/meeting Berlin | Tokyo | New York</code>\n"
        "• <code>/overview</code>"
    )


def _help_text() -> str:
    return (
        "✨ <b>Command spellbook</b>\n\n"
        "<b>Lookup</b>\n"
        "• <code>/now &lt;place&gt;</code> — current local time\n"
        "• <code>/sun &lt;place&gt;</code> — sunrise, sunset, daylight\n"
        "• Send plain text like <code>Tokyo</code> for a quick lookup\n\n"
        "<b>Saved places</b>\n"
        "• <code>/add &lt;place&gt;</code> — save a location\n"
        "• <code>/home &lt;place&gt;</code> — set your anchor location\n"
        "• <code>/overview</code> — pretty clockboard\n"
        "• <code>/remove Tokyo</code> — remove by name or number\n"
        "• <code>/display timezone</code> — choose overview labels\n\n"
        "<b>Comparison & planning</b>\n"
        "• <code>/compare &lt;place&gt;</code> — compare against home\n"
        "• <code>/compare Berlin | Tokyo</code> — direct duel\n"
        "• <code>/meeting</code> — open the ephemeral timezone picker\n"
        "• <code>/manage</code> — visual registry control for saved places\n"
        "• <code>/meeting Berlin | Tokyo | New York</code> — ad hoc meeting magic"
    )


def _map_url(candidate: LocationCandidate) -> str:
    return (
        "https://www.openstreetmap.org/?mlat="
        f"{candidate.latitude:.4f}&amp;mlon={candidate.longitude:.4f}"
        f"#map=10/{candidate.latitude:.4f}/{candidate.longitude:.4f}"
    )


def _flag_emoji(country_code: str | None) -> str:
    if country_code is None or len(country_code) != 2 or not country_code.isalpha():
        return ""
    normalized = country_code.upper()
    offset = ord("🇦") - ord("A")
    return "".join(chr(ord(char) + offset) for char in normalized)


def _clip(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def run_bot(settings: Settings) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.ExtBot").setLevel(logging.WARNING)
    bot = GlobalTimezoneBot(settings)
    application = bot.build_application()
    LOGGER.info("Starting polling bot")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
