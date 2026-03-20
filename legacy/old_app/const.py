### Constants, config ###
SAVE_CONVERSATIONS = True
ADMINS = [62056065]
MAX_LOCATIONS = 10
LOCATION_DISPLAY_CHOICES = {'place': '1⃣ Full Place',
                            'country': '2⃣ Country',
                            'timezone': '3⃣ Timezone'}

big_range = list(range(512))


class BotStates:
    SENDING_ADD_LOCATION, \
    SENDING_HOME_LOCATION, \
    DUMMY3, \
    *rest = big_range


class CallbackActions:
    SET_LOCATION_DISPLAY, \
    REMOVE_LOCATION, \
    SELECT_LOCATION, \
    *rest = big_range
