MAX_LINE_CHARACTERS = 31


def smallcaps(text):
    SMALLCAPS_CHARS = 'ᴀʙᴄᴅᴇғɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ'
    lowercase_ord = 96
    uppercase_ord = 64

    result = ''
    for i in text:
        index = ord(i)
        if 122 >= index >= 97:
            result += SMALLCAPS_CHARS[index - lowercase_ord - 1]
        elif 90 >= index >= 65:
            result += SMALLCAPS_CHARS[index - uppercase_ord - 1]
        elif index == 32:
            result += ' '

    return result


def strikethrough(text: str):
    SPEC = '̶'
    return ''.join([x + SPEC if x != ' ' else ' ' for x in text])


def number_as_emoji(n):
    EMOJI_NUMBERS = '0️⃣1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣8️⃣9️⃣'
    idx = str(n)
    result = []

    for char in idx:
        i = (int(char)) * 3 + 1
        if i == 1:
            i -= 1
        result += EMOJI_NUMBERS[i - 1: i+2]
    return ''.join(result)


def centered(text):
    result = '\n'.join([line.center(MAX_LINE_CHARACTERS) for line in text.splitlines()])
    return result


def success(text):
    return '✅ {}'.format(text)


def failure(text):
    return '❌ {}'.format(text)


def action_hint(text):
    return '💬 {}'.format(text)


def none_action(text):
    return '❎ {}'.format(text)
