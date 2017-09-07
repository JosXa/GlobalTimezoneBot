# -*- coding: utf-8 -*-
from functools import lru_cache

from peewee import *
from telegram import Chat as TelegramChat

import const
import util
from model.basemodel import BaseModel


class Chat(BaseModel):
    chat_id = IntegerField()
    title = CharField(null=True)
    username = CharField(null=True)
    first_name = CharField(null=True)
    last_name = CharField(null=True)

    # preferences
    location_display = CharField(choices=const.LOCATION_DISPLAY_CHOICES.keys(), default='place')

    @property
    def num_locations(self):
        from model import WorldTime
        return WorldTime.select().where(WorldTime.user == self).count()

    def has_added_worldtime(self, wt):
        from model import WorldTime
        return WorldTime.select().where(WorldTime.user == self, WorldTime == wt).exists()

    @staticmethod
    @lru_cache(maxsize=64)
    def from_telegram_object(chat: TelegramChat):
        try:
            chat = Chat.get(Chat.chat_id == chat.id)
        except Chat.DoesNotExist:
            chat = Chat(chat_id=chat.id, first_name=chat.first_name, last_name=chat.last_name)
            if chat.title:
                chat.title = chat.title
            if chat.username:
                chat.username = chat.username
            chat.save()
        return chat

    def __str__(self):
        text = ' '.join([
            '@' + self.username if self.username else self.title if self.title else '',
            self.first_name if self.first_name else '',
            self.last_name if self.last_name else ''
        ])
        return util.escape_markdown(text).encode('utf-8').decode('utf-8')

