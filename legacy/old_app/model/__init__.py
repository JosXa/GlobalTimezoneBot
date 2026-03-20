from peewee import *

from model.chat import Chat
from model.worldtime import WorldTime

if __name__ == "__main__":
    WorldTime.create_table(fail_silently=True)
    Chat.create_table(fail_silently=True)
