import json
import logging
import os
import sys
from typing import List
from uuid import uuid4

from geopy import Location
from geopy import Point
from ordered_set import OrderedSet
from telegram import ChatAction
from telegram import ForceReply
from telegram import InlineKeyboardButton
from telegram import InlineKeyboardMarkup
from telegram import InlineQueryResultArticle
from telegram import InputTextMessageContent
from telegram import KeyboardButton
from telegram import ParseMode
from telegram import ReplyKeyboardMarkup
from telegram.ext import ConversationHandler
from telegram.ext import MessageHandler, \
    CallbackQueryHandler, Filters, InlineQueryHandler
from telegram.ext import RegexHandler
from telegram.ext import Updater, CommandHandler

import captions
import const
import mdformat
import util
from components import basic
from const import BotStates
from const import CallbackActions
from lib.markdownformatter import MarkdownFormatter
from model.chat import Chat
from model.chathome import ChatHome
from model.worldtime import WorldTime

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)


def start(bot, update, args):
    user = Chat.from_telegram_object(update.effective_message.chat)
    query = None

    if args:
        command = args[0]
        if len(args) > 1:
            query = args[1:]

        if command == 'add':
            return provide_location(bot, update, query)

    # otherwise
    main_menu(bot, update)


def _main_menu_buttons():
    return [
        [KeyboardButton(captions.OVERVIEW)],
        [KeyboardButton(captions.ADD_LOCATION), KeyboardButton(captions.REMOVE_LOCATION)],
        [KeyboardButton(captions.SET_HOME_LOCATION), KeyboardButton(captions.SET_DISPLAY)]
    ]


def main_menu(bot, update, message=None):
    if not message:
        message = mdformat.action_hint("Send me the name of a location anywhere in the world!")
    reply_markup = ReplyKeyboardMarkup(_main_menu_buttons(), resize_keyboard=True)
    bot.sendMessage(update.effective_chat.id, message, reply_markup=reply_markup)
    return ConversationHandler.END


def inlinequery(bot, update):
    query_text = update.inline_query.query.lower()
    user = Chat.from_telegram_object(update.effective_chat)
    articles = OrderedSet()
    user_zones = WorldTime.select().where(WorldTime.user == user)

    def zone_article(zone: WorldTime):
        text = "It is a {} in *{}*:\n\n".format(zone.weekday_formatted, zone.country)
        text += zone.md_str
        return InlineQueryResultArticle(
            id=zone.place,
            title=zone.place + ' ' + zone.flag_emoji,
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
    update.effective_message.reply_text("Help message")

# def _favorize_button(wt: WorldTime, chat: Chat):
#     if chat.has_added_worldtime(wt):
#         return InlineKeyboardButton("")

def simple_location(bot, update, chat_data, location=None):
    chat_data.setdefault('callbacks', {})
    cid = update.effective_chat.id
    mid = util.mid_from_update(update)
    bot.sendChatAction(update.effective_chat.id, ChatAction.FIND_LOCATION)
    chat = Chat.from_telegram_object(update.effective_message.chat)

    if location is not None:
        locations = [location]
    elif update.effective_message.location:
        point = Point(update.effective_message.location.latitude, update.effective_message.location.longitude)
        locations = WorldTime.reverse_geocode(point)
    elif update.effective_message.text:
        text = update.effective_message.text
        locations = WorldTime.geocode(text)
    else:
        raise ValueError("No location entity or text supplied.")

    if not locations:
        return fail(bot, update, "Sorry, I couldn't find a location for that.")

    if len(locations) > 1:
        uuid = str(uuid4())

        second_cb = lambda b, u, cd, **kwargs: simple_location(b, u, cd, **kwargs)
        first_cb = lambda b, u, cd: select_location(b, u, cd, locations, second_cb)
        chat_data['callbacks'][uuid] = {'method': first_cb}
        buttons = [InlineKeyboardButton('Not what I meant', callback_data=uuid)]
    else:
        buttons = []

    wt = WorldTime.from_location(locations[0])
    if wt is None:
        fail(bot, update, "Sorry, something went wrong parsing this location "
                          "from Google Maps. Try something different 🐻")

    # buttons.append(_favorize_button(wt, chat))
    reply_markup = InlineKeyboardMarkup(util.build_menu(buttons, 1))

    bot.formatter.send_or_edit(cid, wt.md_str, to_edit=mid, reply_markup=reply_markup)


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
    user = Chat.from_telegram_object(update.effective_message.chat)
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


def add_location_text(bot, update):
    update.effective_message.reply_text(
        "Which location would you like to add?\n{}, or /cancel".format(
            util.action_hint("Send a venue")),
        reply_markup=ForceReply(), quote=True)
    return BotStates.SENDING_ADD_LOCATION


def select_location(bot, update, chat_data, locations: List[Location], callback):
    buttons = []
    cid = update.effective_chat.id
    mid = util.mid_from_update(update)
    for loc in locations:
        uuid = str(uuid4())
        chat_data.setdefault('callbacks', {})
        chat_data['callbacks'][uuid] = {'method': callback, 'location': loc}
        buttons.append(InlineKeyboardButton(loc.address, callback_data=uuid))

    reply_markup = InlineKeyboardMarkup(util.build_menu(buttons, 1))
    bot.formatter.send_or_edit(
        cid,
        mdformat.action_hint("Please select the location that works best for you"),
        to_edit=mid,
        reply_markup=reply_markup
    )


def save_location(bot, update, chat_data, location: Location, as_home=False):
    chat = Chat.from_telegram_object(update.effective_chat)

    wt = WorldTime.lookup(location)
    if not wt:
        return fail(bot, update)
    wt.user = chat
    wt.save()

    if as_home:
        home = ChatHome.set(chat, wt)
        return main_menu(bot, update, util.success("🏠 {} set as your home location, well done! You can now "
                                                   "calculate time differences ".format(home.md_str)))
    else:
        if WorldTime.select().where(WorldTime.user == chat, WorldTime.place == wt.place).exists():
            return fail(bot, update, "You have already added {}.".format(wt.place), 'action_hint')
        return main_menu(bot, update, util.success("{} added. Now try /overview".format(wt.md_place)))


def provide_location(bot, update, chat_data, args=None, as_home=False):
    chat = Chat.from_telegram_object(update.effective_chat)

    if chat.num_locations == const.MAX_LOCATIONS:
        return fail(bot, update, "Sorry, you can't add more than {} locations.".format(const.MAX_LOCATIONS))

    if not args:
        if update.effective_message.location:
            point = Point(update.effective_message.location.latitude, update.effective_message.location.longitude)
            locations = WorldTime.reverse_geocode(point)
            if not locations:
                return fail(bot, update)
            if len(locations) == 1:
                return save_location(bot, update, chat_data, locations[0], as_home)

            cb = lambda b, u, cd, **kwargs: save_location(b, u, cd, as_home=as_home, **kwargs)
            return select_location(bot, update, chat_data, locations, callback=cb)
        else:
            update.effective_message.reply_text(
                util.action_hint(
                    "Please use this command with an argument. For example:\n\n/addlocation toronto canada"))
            return ConversationHandler.END
    else:
        query = args
        if isinstance(args, list):
            query = ' '.join(args)
        locations = WorldTime.geocode(query)
        if len(locations) == 1:
            return save_location(bot, update, chat_data, locations[0], as_home)
        cb = lambda b, u, cd, **kwargs: save_location(b, u, cd, as_home=as_home, **kwargs)
        return select_location(bot, update, chat_data, locations, callback=cb)


def remove_location(bot, update):
    chat_id = update.effective_chat.id
    user = Chat.get(Chat.chat_id == chat_id)
    user_wts = WorldTime.select().where(WorldTime.user == user)

    buttons = [InlineKeyboardButton('✖️ {}'.format(x.place),
                                    callback_data=util.callback_for_action(
                                        CallbackActions.REMOVE_LOCATION, {'id': x.id})) for x in user_wts]
    reply_markup = InlineKeyboardMarkup(util.build_menu(buttons, 2))
    util.send_or_edit_md_message(bot, chat_id, mdformat.action_hint('Select a location to remove'),
                                 to_edit=util.mid_from_update(update), reply_markup=reply_markup)


def set_home_location(bot, update):
    update.effective_message.reply_text(
        "By setting your home location, I can calculate the time difference "
        "to your other locations.\n{}, or /cancel".format(
            util.action_hint("Send your home place as text or location")),
        reply_markup=ForceReply(), quote=True)
    return BotStates.SENDING_HOME_LOCATION


def fail(bot, update, message=None, severity='error'):
    if not message:
        message = "Either Google Maps has a bad day, or you're fucking swimming and shit. 🐳"
    if severity in ['warning', 'none_action']:
        text = mdformat.none_action(message)
    elif severity == 'action_hint':
        text = mdformat.action_hint(message)
    else:
        text = mdformat.failure(message)

    main_menu(bot, update, text)
    return ConversationHandler.END


def cancel(bot, update):
    main_menu(bot, update)
    return ConversationHandler.END


def callback_router(bot, update, chat_data):
    chat_data.setdefault('callbacks', {})
    if update.callback_query.data in chat_data['callbacks']:
        callback = chat_data['callbacks'][update.callback_query.data]

        # put payload into kwargs
        payload = {k: v for k, v in callback.items() if k != 'method'}
        update.callback_query.answer()
        return callback['method'](bot, update, chat_data, **payload)

    obj = json.loads(str(update.callback_query.data))
    uid = util.uid_from_update(update)
    if 'a' in obj:
        action = obj['a']

        if action == CallbackActions.SET_LOCATION_DISPLAY:
            user = Chat.get(Chat.chat_id == uid)
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

    conv_handler = ConversationHandler(
        entry_points=[RegexHandler(captions.ADD_LOCATION, add_location_text),
                      RegexHandler(captions.SET_HOME_LOCATION, set_home_location)],

        states={
            BotStates.SENDING_ADD_LOCATION: [
                MessageHandler(Filters.text | Filters.location,
                               lambda bot, update, chat_data: provide_location(
                                   bot, update, chat_data, update.message.text),
                               pass_chat_data=True),
                CommandHandler('cancel', cancel)],
            BotStates.SENDING_HOME_LOCATION: [
                MessageHandler(Filters.text | Filters.location,
                               lambda bot, update, chat_data: provide_location(
                                   bot, update, chat_data, update.message.text, as_home=True),
                               pass_chat_data=True),
                CommandHandler('cancel', cancel)]
        },

        fallbacks=[CommandHandler('cancel', cancel)]
    )

    dp.add_handler(conv_handler)

    dp.add_handler(CommandHandler('start', start, pass_args=True))
    dp.add_handler(CommandHandler('help', help))
    dp.add_handler(CommandHandler('addlocation', provide_location, pass_args=True))
    dp.add_handler(CommandHandler('remlocation', remove_location))
    dp.add_handler(CommandHandler('sethome', set_home_location, pass_args=True))
    dp.add_handler(CommandHandler('display', location_display))
    dp.add_handler(CommandHandler('overview', overview))

    dp.add_handler(RegexHandler(captions.OVERVIEW, overview))
    dp.add_handler(RegexHandler(captions.REMOVE_LOCATION, remove_location))
    dp.add_handler(RegexHandler(captions.SET_DISPLAY, location_display))

    dp.add_handler(InlineQueryHandler(inlinequery))
    dp.add_handler(CallbackQueryHandler(callback_router, pass_chat_data=True))
    dp.add_error_handler(error)
    dp.add_handler(CommandHandler('cancel', cancel))
    dp.add_handler(
        MessageHandler((Filters.text & Filters.private) | Filters.location, simple_location, pass_chat_data=True))

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
