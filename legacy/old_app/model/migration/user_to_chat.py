import os

from decouple import config
from playhouse.migrate import SqliteMigrator, IntegerField, migrate
from playhouse.sqlite_ext import SqliteExtDatabase

from model import Chat

db_path = config('DATABASE_URI', default=os.path.expanduser('~/data/globaltimezonebot.sqlite3'))
db = SqliteExtDatabase(db_path)

migrator = SqliteMigrator(db)


with db.transaction():
    migrate(
        migrator.rename_table('user', 'chat')
    )

Chat.drop_table()
Chat.create_table()
