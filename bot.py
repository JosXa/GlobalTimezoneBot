import datetime
import json
import logging
import os
import sys

import re
import regex
from ordered_set import OrderedSet
from telegram import InlineQueryResultArticle
from telegram import InputTextMessageContent
from telegram import KeyboardButton
from telegram import ParseMode
from telegram import ReplyKeyboardMarkup
from telegram import ReplyMarkup
from telegram.ext import RegexHandler

import captions
import pycountry
from geopy import geocoders
from telegram import ChatAction
from telegram import InlineKeyboardButton
from telegram import InlineKeyboardMarkup
from telegram.ext import MessageHandler, \
    CallbackQueryHandler, Filters, InlineQueryHandler
from telegram.ext import Updater, CommandHandler

import const
import mdformat
import util
from components import basic
from const import CallbackActions
from lib.markdownformatter import MarkdownFormatter
from model.user import User
from model.worldtime import WorldTime
from sunrise import sun

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)


def start(bot, update, args):
    user = User.from_telegram_object(update.message.from_user)
    query = ' '.join(args)

    if query == 'add':
        add_location(bot, update)
    else:
        main_menu(bot, update)


def main_menu(bot, update):
    chat_id = util.cid_from_update(update)
    buttons = [
        [KeyboardButton(captions.OVERVIEW)],
        [KeyboardButton(captions.ADD_LOCATION), KeyboardButton(captions.REMOVE_LOCATION)],
        [KeyboardButton(captions.SET_HOME_LOCATION), KeyboardButton(captions.SET_DISPLAY)]
    ]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    bot.sendMessage(chat_id, mdformat.action_hint("Send me the name of a location anywhere in the world!"),
                    reply_markup=reply_markup)


def inlinequery(bot, update):
    query_text = update.inline_query.query.lower()
    user = User.from_telegram_object(update.effective_user)
    articles = OrderedSet()
    user_zones = WorldTime.select().where(WorldTime.user == user)

    def zone_article(zone: WorldTime):
        text = "It is a {} in *{}*:\n\n".format(zone.weekday_formatted, zone.country)
        text += zone.md_str
        return InlineQueryResultArticle(
            id=zone.place,
            title=zone.place + ' ' +zone.flag_emoji,
            description=zone.datetime_formatted,
            input_message_content=InputTextMessageContent(
                message_text=text,
                parse_mode=ParseMode.MARKDOWN,
            )
        )

    try:
        wt = WorldTime.lookup(query_text)
    except:
        wt = None

    if wt:
        articles.add(zone_article(wt))

    for wt in user_zones:
        articles.add(zone_article(wt))

    update.inline_query.answer(articles, cache_time=300, is_personal=False,
                               switch_pm_text="➕ Add a new location",
                               switch_pm_parameter="add")

def error(bot, update, error):
    log.error(error)


def help(bot, update):
    update.message.reply_text("Help message")


def plaintext(bot, update):
    text = update.message.text
    chat_id = util.cid_from_update(update)
    bot.sendChatAction(chat_id, ChatAction.FIND_LOCATION)

    user = User.from_telegram_object(update.message.from_user)
    error = False
    wt = None
    try:
        wt = WorldTime.lookup(text)
    except:
        error = True
    if wt:
        update.message.reply_text(wt.md_str, parse_mode='Markdown')
    else:
        error = True
    if error:
        update.message.reply_text(util.failure("Sorry, I couldn't find a location for that."))


def _overview_text(wts, user):
    wts.sort(key=lambda t: t.comparable)
    txt = '\n'
    txt += '🌎🌍🌏🌎🌍🌏🌎🌍🌏🌎\n'
    last_day = None
    for w in wts:
        if last_day != w.weekday_formatted:
            txt += '{}\n'.format(w.weekday_formatted)
        txt += w.sun_emoji + ' '
        txt += w.time_formatted + ' '
        txt += w.flag_emoji + ' '
        if user.location_display == 'place':
            txt += w.place
        elif user.location_display == 'country':
            txt += w.country
        elif user.location_display == 'timezone':
            txt += w.timezone
        txt += '\n'
        last_day = w.weekday_formatted

    return txt

def overview(bot, update):
    chat_id = util.cid_from_update(update)
    user = User.from_telegram_object(update.message.from_user)
    bot.sendChatAction(chat_id, ChatAction.FIND_LOCATION)
    wts = list(WorldTime.select().where(WorldTime.user == user))
    if len(wts) == 0:
        # send some defaults
        queries = ['moscow', 'cologne', 'thailand', 'shanghai', 'denver', 'Australia', 'toronto', 'ghana', 'ireland',
                   'japan',
                   'vietnam']
        wts = [WorldTime.lookup(q) for q in queries]

    txt = _overview_text(wts, user)
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton('Share', switch_inline_query='Overview')]])
    util.send_md_message(bot, chat_id, txt, reply_markup=reply_markup)


def location_display(bot, update):
    chat_id = util.cid_from_update(update)
    buttons = [InlineKeyboardButton(value, callback_data=util.callback_for_action(
        CallbackActions.SET_LOCATION_DISPLAY, {'c': key})) for key, value in const.LOCATION_DISPLAY_CHOICES.items()]
    reply_markup = InlineKeyboardMarkup([buttons])
    options = util.action_hint("What format would you like to use for locations?")
    options += "\n\n1⃣ Toronto, ON, Canada\n2⃣ Canada\n3⃣ America/Regina"
    util.send_md_message(bot, chat_id, options, reply_markup=reply_markup)


def add_location(bot, update, args=None):
    chat_id = util.cid_from_update(update)
    user = User.from_telegram_object(update.message.from_user)

    if update.message.text == captions.ADD_LOCATION:
        update.message.reply_text('Please use the command for now: /addlocation toronto')
        return

    if args:
        query = ' '.join(args)
        wt = WorldTime.lookup(query)
        wt.user = user
        if WorldTime.select().where(WorldTime.user == user, WorldTime.place == wt.place).exists():
            util.send_md_message(bot, chat_id, mdformat.none_action("You have already added {}.".format(wt.place)))
            return
        if wt.flag_emoji is None:
            util.send_md_message(bot, chat_id, "Unfortunately, I couldn't find the associated country flag emoji...")
        if wt:
            wt.save()
            update.message.reply_text(util.success("{} added. Now try /overview".format(wt.place)))
        else:
            update.message.reply_text(util.failure("Sorry, I couldn't find a location for {}.".format(query)))
    else:
        update.message.reply_text(
            util.action_hint("Please use this command with an argument. For example:\n\n/addlocation toronto canada"))
        return


def remove_location(bot, update):
    chat_id = util.cid_from_update(update)
    user = User.get(User.chat_id == chat_id)
    user_wts = WorldTime.select().where(WorldTime.user == user)

    buttons = [InlineKeyboardButton('✖️ {}'.format(x.place),
                                    callback_data=util.callback_for_action(
                                        CallbackActions.REMOVE_LOCATION, {'id': x.id})) for x in user_wts]
    reply_markup = InlineKeyboardMarkup(util.build_menu(buttons, 2))
    util.send_or_edit_md_message(bot, chat_id, mdformat.action_hint('Select a location to remove'),
                                 to_edit=util.mid_from_update(update), reply_markup=reply_markup)


def set_home_location(bot, update):
    update.message.reply_text('Not yet implemented. Stay tuned!')
    pass


def callback_router(bot, update, chat_data):
    obj = json.loads(str(update.callback_query.data))
    uid = util.uid_from_update(update)
    if 'a' in obj:
        action = obj['a']

        if action == CallbackActions.SET_LOCATION_DISPLAY:
            user = User.get(User.chat_id == uid)
            user.location_display = obj['c']
            user.save()
            update.callback_query.answer(
                text='Format set to {}.'.format(const.LOCATION_DISPLAY_CHOICES[user.location_display]))
        if action == CallbackActions.REMOVE_LOCATION:
            wt = WorldTime.get(WorldTime.id == obj['id'])
            wt.delete_instance()
            remove_location(bot, update)


def main():
    try:
        BOT_TOKEN = str(os.environ['TG_TOKEN'])
    except Exception:
        BOT_TOKEN = str(sys.argv[1])
    try:
        PORT = str(os.environ['PORT'])
    except Exception:
        PORT = None
    try:
        URL = str(os.environ['URL'])
    except Exception:
        URL = None

    updater = Updater(BOT_TOKEN, workers=2)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher
    updater.bot.formatter = MarkdownFormatter(updater.bot)

    dp.add_handler(CommandHandler('start', start, pass_args=True))
    dp.add_handler(CommandHandler('help', help))
    dp.add_handler(CommandHandler('addlocation', add_location, pass_args=True))
    dp.add_handler(CommandHandler('remlocation', remove_location))
    dp.add_handler(CommandHandler('sethome', set_home_location, pass_args=True))
    dp.add_handler(CommandHandler('display', location_display))
    dp.add_handler(CommandHandler('overview', overview))

    dp.add_handler(RegexHandler(captions.OVERVIEW, overview))
    dp.add_handler(RegexHandler(captions.ADD_LOCATION, add_location))
    dp.add_handler(RegexHandler(captions.REMOVE_LOCATION, remove_location))
    dp.add_handler(RegexHandler(captions.SET_HOME_LOCATION, set_home_location))
    dp.add_handler(RegexHandler(captions.SET_DISPLAY, location_display))

    dp.add_handler(InlineQueryHandler(inlinequery))
    dp.add_handler(CallbackQueryHandler(callback_router, pass_chat_data=True))
    dp.add_error_handler(error)
    dp.add_handler(MessageHandler(Filters.text, plaintext))

    basic.register(dp)

    if PORT and URL:
        updater.start_webhook(listen='0.0.0.0', port=PORT, url_path=BOT_TOKEN)
        updater.bot.setWebhook(URL +
                               BOT_TOKEN)
    else:
        updater.start_polling()

    log.info('Listening...')
    updater.idle()


if __name__ == '__main__':
    main()
