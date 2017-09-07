# -*- coding: utf-8 -*-
from peewee import *

import const
import util
from model import Chat
from model import WorldTime
from model.basemodel import BaseModel


class ChatHome(BaseModel):
    chat = ForeignKeyField(Chat, unique=True)
    home = ForeignKeyField(WorldTime)

    @staticmethod
    def lookup(chat):
        try:
            return ChatHome.get(ChatHome.chat == chat)
        except ChatHome.DoesNotExist:
            return None

    @staticmethod
    def set(chat, home):
        current = ChatHome.lookup(chat)

        if current:
            current.home = home
            current.save()
            return current
        else:
            now = ChatHome(chat=chat, home=home)
            now.save()
            return now

    @property
    def md_str(self):
        return '🏠 {}'.format(self.home.md_place)
