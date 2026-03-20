import json
import logging
from functools import wraps
from pprint import pprint
from typing import Callable, Dict

from telegram import Update
from telegram.ext.handler import Handler


class InlineCallbackHandler(Handler):
    def __init__(self,
                 context,
                 action,
                 callback,
                 pass_update_queue=False,
                 pass_job_queue=False,
                 pass_groups=False,
                 pass_groupdict=False,
                 pass_user_data=False,
                 pass_chat_data=False,
                 auto_answer=True):
        """
        This class maps an action to the appropriate callback as the counterpart to InlineCallbackButton.

        Pass a function ``serialize(callback_data, update)`` returning a dict of values to create objects for the parameters
        you specified in the parameters of ``InlineCallbackButton``.

        Example:
            Assuming you want to create an object `User` in your object-relational-mapper (ORM)

            ```
            def serialize_objects(data, update):
                context = dict()
                context['user'] = User.get_or_create(id=data['id])
                return context
            ```

            You can then pass this function as an argument to the constructor.

            ``InlineCallbackHandler(CallbackActions.CREATE_USER, create_user, serialize=serialize_objects)``

        :param action: The action to use
        :param callback: The corresponding callback handler
        :param serialize: A serialization function with 2 arguments (data, update)
        :param pass_update_queue:
        :param pass_job_queue:
        :param pass_user_data:
        :param pass_chat_data:
        :param auto_answer: Whether the Callback Query should be answered automatically after the handler is done
        """

        super(InlineCallbackHandler, self).__init__(
            callback,
            pass_update_queue=pass_update_queue,
            pass_job_queue=pass_job_queue,
            pass_user_data=pass_user_data,
            pass_chat_data=pass_chat_data)

        self.context = context
        self.action = action
        self.pass_groups = pass_groups
        self.pass_groupdict = pass_groupdict
        self.auto_answer = auto_answer
        self.log = logging.getLogger(__name__)

    def check_update(self, update):
        print('checking')
        pprint(self.context)
        if isinstance(update, Update) and update.callback_query:
            if self.action:
                ctx = self.context.retrieve(update)
                print(ctx)
                print(type(ctx))
                print()
                print(update.callback_query.data)
                print(type(int(update.callback_query.data)))
                return ctx['id'] == int(update.callback_query.data)
            return False

    def handle_update(self, update, dispatcher):
        optional_args = self.collect_optional_args(dispatcher, update)

        if self.auto_answer:
            # automatically answer callback queries

            def wrapped(callback, bot, update, *args, **kwargs):
                callback(bot, update, **optional_args)
                bot.answerCallbackQuery(update.callback_query.id)

            return wrapped(self.callback, dispatcher.bot, update, **optional_args)
        else:
            return self.callback(dispatcher.bot, update, **optional_args)
