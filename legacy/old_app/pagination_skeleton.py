import json
from uuid import uuid4
from telegram import Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyMarkup
import util
from custemoji import Emoji


class Pagination(object):
    NEXT_PAGE_ACTION = 'nxt'
    PREV_PAGE_ACTION = 'prv'

    def __init__(self, items, domain=None):
        """

        :param items: List of tuples (bot, text=..., reply_markup=...) ???
        :param domain:
        """
        self._current_page = 0
        self._items = items
        self._size = len(items)
        self._edit_message_id = None
        self._prev_btn_caption = Emoji.BLACK_RIGHT_POINTING_DOUBLE_TRIANGLE
        self._next_btn_caption = Emoji.BLACK_LEFT_POINTING_DOUBLE_TRIANGLE
        if domain:
            self._domain = domain
        else:
            self._domain = uuid4()[:8]

    def get_callback_router(self):
        def router(bot: Bot, update: Update):
            obj = json.loads(str(update.callback_query.data))
            if 'a' in obj:
                action = obj['a']

                if action == self.NEXT_PAGE_ACTION:
                    self.next_page(bot, update)
                if action == self.PREV_PAGE_ACTION:
                    self.previous_page(bot, update)

        return router

    def update(self, bot, **args):
        if 'reply_markup' in args:
            reply_markup = args['reply_markup']
            if isinstance(reply_markup, InlineKeyboardMarkup):
                args['reply_markup'] = self._insert_markup_buttons(reply_markup)
            else:
                raise ValueError("Can only update InlineKeyboardMarkups")
        if self._edit_message_id is None:
            msg = bot.sendMessage(**args)
            self._edit_message_id = msg.message_id
            return msg
        else:
            return bot.editMessageText(message_id=self._edit_message_id, **args)

    def _get_current_page(self):
        return self._items[self._current_page]

    def _insert_markup_buttons(self, markup: InlineKeyboardMarkup):
        buttons = markup.inline_keyboard
        if self.has_next_page:
            buttons[-1].insert(0, InlineKeyboardButton(self._next_btn_caption,
                                                       callback_data=util.callback_str_from_dict({
                                                           'a': self.NEXT_PAGE_ACTION,
                                                           'd': self._domain
                                                       })))
        if self.has_prev_page:
            buttons[-1].append(InlineKeyboardButton(self._prev_btn_caption,
                                                    callback_data=util.callback_str_from_dict({
                                                        'a': self.NEXT_PAGE_ACTION,
                                                        'd': self._domain
                                                    })))
        markup.inline_keyboard = buttons
        return markup

    @property
    def has_next_page(self):
        return self._current_page < self._size - 1

    @property
    def has_prev_page(self):
        return self._current_page > 0

    def next_page(self, bot, update):
        pass

    def previous_page(self, bot, update):
        pass
