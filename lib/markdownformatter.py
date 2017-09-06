import traceback

from telegram import Message
from telegram import ParseMode
from telegram import ReplyKeyboardRemove
from telegram.error import BadRequest

from lib.mdformat import success, failure, action_hint, none_action


class MarkdownFormatter:
    def __init__(self, bot):
        self.bot = bot

    def send_message(self, chat_id, text: str, **kwargs):
        if 'disable_web_page_preview' not in kwargs:
            kwargs['disable_web_page_preview'] = True
        return self.bot.sendMessage(chat_id, text, parse_mode=ParseMode.MARKDOWN, **kwargs)

    def send_success(self, chat_id, text: str, add_punctuation=True, reply_markup=None, **kwargs):
        if add_punctuation:
            if text[-1] != '.':
                text += '.'

        if not reply_markup:
            reply_markup = ReplyKeyboardRemove()
        return self.bot.sendMessage(
            chat_id,
            success(text),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
            **kwargs)

    def send_failure(self, chat_id, text: str, **kwargs):
        text = str.strip(text)
        if text[-1] != '.':
            text += '.'
        return self.bot.sendMessage(
            chat_id,
            failure(text),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            **kwargs)

    def send_action_hint(self, chat_id, text: str, **kwargs):
        if text[-1] == '.':
            text = text[0:-1]
        return self.bot.sendMessage(
            chat_id,
            action_hint(text),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            **kwargs)

    def send_none_action(self, chat_id, text: str, **kwargs):
        if text[-1] == '.':
            text = text[0:-1]
        return self.bot.sendMessage(
            chat_id,
            none_action(text),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            **kwargs)

    def send_or_edit(self, chat_id, text, to_edit=None, **kwargs):
        mid = to_edit
        if isinstance(to_edit, Message):
            mid = to_edit.message_id

        try:
            if to_edit:
                return self.bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=mid,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                    **kwargs
                )

            return self.send_message(chat_id, text=text, **kwargs)
        except BadRequest as e:
            if 'not modified' in e.message.lower():
                pass
            else:
                traceback.print_exc()
