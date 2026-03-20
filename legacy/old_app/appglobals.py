import os

from decouple import config
from peewee import *

# get root directory of this project
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

_db = None


def db():
    global _db
    if not _db:
        db_path = config('DATABASE_URI', default=os.path.expanduser('~/data/globaltimezonebot.sqlite3'))
        _db = SqliteDatabase(db_path)
    return _db


# globals
db = db()
