from pprint import pprint
from telegram import ParseMode
from telegram import Update

import const
from const import *
import util
from const import BotStates
from custemoji import Emoji
from telegram import ChatAction
from telegram import InlineQueryResultArticle, ParseMode, \
    InputTextMessageContent, TelegramError
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import MessageHandler, \
    CallbackQueryHandler, Filters, RegexHandler, InlineQueryHandler, ConversationHandler, Job
from telegram.ext import Updater, CommandHandler


def menu(bot, update: Update):
    chat_id = util.chat_id_from_update(update)
