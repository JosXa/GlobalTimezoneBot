import datetime

import math
import urllib

import util
import pytz
from pprint import pprint
import ephem

import pycountry
from geopy import geocoders

from custemoji import Emoji
from model.basemodel import BaseModel
from peewee import *

from model.user import User
from sunrise import sun

"""
### TODO:
# LookupErrors:
- Russia

"""


class WorldTime(BaseModel):
    place = CharField(unique=True)
    user = ForeignKeyField(User)
    country = CharField()
    lat = CharField()
    lon = CharField()
    timezone = CharField()
    flag_emoji = CharField()

    GEOCODER = geocoders.GoogleV3()

    @staticmethod
    def lookup(query):
        place, (lat, lon) = WorldTime.GEOCODER.geocode(query, exactly_one=True)
        lat = float(lat)
        lon = float(lon)
        try:
            if place is None:
                return None
            country_query = place.split(', ')[-1]
            replacements = {'russia': 'russian federation',
                            'vietnam': 'viet nam',
                            'uk': 'united kingdom',
                            }
            repl = replacements.get(country_query.lower())
            if repl:
                country_query = repl
            country = pycountry.countries.lookup(country_query)

            try:
                return WorldTime.get(WorldTime.place == place)
            except WorldTime.DoesNotExist:
                pass

            tz = WorldTime.GEOCODER.timezone((lat, lon))

            flg = WorldTime.emoji_from_country(country.alpha_2)

            print('Found {}: {}'.format(query, place))
            return WorldTime(place=place, country=country.name, lat=lat, lon=lon, timezone=tz.zone, flag_emoji=flg)
        except Exception:
            print('Error trying to retrieve {}: {}'.format(query, place))
            return None

    @property
    def datetime_formatted(self):
        return self.localdatetime.strftime('%a, %m-%d-%Y %H:%M')

    @property
    def date_formatted(self):
        return self.localdatetime.strftime('%a, %m-%d-%Y')

    @property
    def time_formatted(self):
        return self.localdatetime.strftime('%H:%M')

    @property
    def weekday_formatted(self):
        return self.localdatetime.strftime('%A')

    @property
    def localdatetime(self):
        return datetime.datetime.now(pytz.timezone(self.timezone))

    @property
    def comparable(self):
        normal = datetime.datetime(2009, 9, 1)
        return pytz.timezone(self.timezone).utcoffset(normal)

    def time_difference(self, worldtime):
        return self.localdatetime - worldtime.localdatetime

    def time_difference_formatted(self, worldtime):
        return '{} h'.format(self.time_difference(worldtime))

    @staticmethod
    def emoji_from_country(country):

        def flag(code):
            offset = ord('🇦') - ord('A')
            return chr(ord(code[0]) + offset) + chr(ord(code[1]) + offset)

        try:
            country = pycountry.countries.lookup(country)
            return flag(country.alpha_2)
        except Exception:
            return None

    @property
    def md_str(self):
        loc_md = "[{} Show Location](https://www.google.de/maps/search/{})".format(
            Emoji.ROUND_PUSHPIN,
            urllib.parse.quote_plus(self.place),
        )
        return '{}{}\n🕰 {}\n🗓 {}\n🕜 {}\n{}'.format(
            (self.flag_emoji + ' ') if self.flag_emoji else '',
            util.escape_markdown(self.place),
            util.escape_markdown(self.time_formatted),
            util.escape_markdown(self.date_formatted),
            util.escape_markdown(self.timezone),
            loc_md)

    @property
    def sun_emoji(self):
        s = sun(lat=self.lat, long=self.lon)
        when = datetime.datetime.now()
        sunrise = s.sunrise(when)
        solarnoon = s.solarnoon(when)
        sunset = s.sunset(when)
        if sunrise < datetime.datetime.now().time() < sunset:
            return '☀️'
        else:
            return '🌒'

    @staticmethod
    def country_list():
        return list(pycountry.countries)


if __name__ == '__main__':
    wt = WorldTime.lookup('china')
    print(wt)
    print(wt.datetime_formatted)
    pprint(wt.to_dict())
