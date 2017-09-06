from peewee import *

from model.user import User
from model.worldtime import WorldTime

if __name__ == "__main__":
    WorldTime.create_table(fail_silently=True)
    User.create_table(fail_silently=True)
