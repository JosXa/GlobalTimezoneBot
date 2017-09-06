import logging
import os
import sys
import time

from telegram import ReplyKeyboardRemove
from telegram.ext import CommandHandler

import util
from util import restricted

logging.basicConfig(format='%(levelname)s: %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)


def error(bot, update, error):
    log.exception(error)


def remove_keyboard(bot, update):
    update.message.reply_text("Keyboard removed.", reply_markup=ReplyKeyboardRemove())


@restricted
def restart(bot, update):
    chat_id = util.uid_from_update(update)
    util.send_message_success(bot, chat_id, "Bot is restarting...")
    time.sleep(0.2)
    os.execl(sys.executable, sys.executable, *sys.argv)


def register(dp):
    dp.add_handler(CommandHandler('r', restart))
    dp.add_handler(CommandHandler("removekeyboard", remove_keyboard))
