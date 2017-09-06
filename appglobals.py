import os
from peewee import *

# get root directory of this project
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

""" Configuration """
DB_NAME = "database.db"

_db = None


def db():
    global _db
    if not _db:
        db_path = os.path.join(ROOT_DIR, DB_NAME)
        _db = SqliteDatabase(db_path)
    return _db


# globals
db = db()
