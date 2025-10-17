import urllib.parse

from src.bot.keyboards.base import AutoKeyboard
from src.bot.keyboards.callbackdata import (
    ChatSelect,
    ChatsPaginate,
    GenerateInvite,
    MuteAction,
    NickListPaginate,
    UnmuteAction,
)


class start(AutoKeyboard):
    def __init__(self):
        self.row(self.cb("Все чаты", "all_chats"))
        self.row(self.cb("Помощь", "command_help"))


class chats_paginate(AutoKeyboard):
    def __init__(self, chats: list[tuple[int, str]], page: int = 0, maxpage: int = 0):
        for i in range(0, len(chats), 2):
            row_buttons = [self.cb(chats[i][1], ChatSelect(chat_id=chats[i][0]))]
            if i + 1 < len(chats):
                row_buttons.append(
                    self.cb(chats[i + 1][1], ChatSelect(chat_id=chats[i + 1][0]))
                )
            self.row(*row_buttons)

        row = []
        if page > 0:
            row.append(self.cb("Назад", ChatsPaginate(page=page - 1)))
        if maxpage > 0:
            row.append(self.cb(f"[{page + 1}/{maxpage + 1}]", ChatsPaginate(page=page)))
        if page < maxpage:
            row.append(self.cb("Вперёд", ChatsPaginate(page=page + 1)))
        if row:
            self.row(*row)

        self.row(self.cb("Назад", "start"))


class chat_card(AutoKeyboard):
    def __init__(self, chat_id: int, invite_url: str | None = None):
        self.row(
            self.cb(
                "Получить новую пригласительную ссылку", GenerateInvite(chat_id=chat_id)
            )
        )
        if invite_url:
            self.row(
                self.url(
                    "Поделиться ссылкой",
                    f"https://t.me/share/url?url={urllib.parse.quote(invite_url, safe='')}",
                )
            )
        self.row(self.cb("Назад", "all_chats"))


class help(AutoKeyboard):
    def __init__(self):
        self.row(self.cb("Назад", "start"))


class nick_list_paginate(AutoKeyboard):
    def __init__(self, page: int, maxpage: int, chat_id: int):
        row = []
        if page > 0:
            row.append(
                self.cb("Назад", NickListPaginate(chat_id=chat_id, page=page - 1))
            )
        if maxpage > 0:
            row.append(
                self.cb(
                    f"[{page + 1}/{maxpage + 1}]",
                    NickListPaginate(chat_id=chat_id, page=page),
                )
            )
        if page < maxpage:
            row.append(
                self.cb("Вперёд", NickListPaginate(chat_id=chat_id, page=page + 1))
            )
        if row:
            self.row(*row)


class mute_actions(AutoKeyboard):
    def __init__(self, user_id: int):
        self.row(
            self.cb("🔇 Мут 1ч", MuteAction(user_id=user_id, duration="1h")),
            self.cb("🔇 Мут 6ч", MuteAction(user_id=user_id, duration="6h")),
            self.cb("🔇 Мут 24ч", MuteAction(user_id=user_id, duration="24h")),
        )
        self.row(self.cb("🔊 Снять мут", UnmuteAction(user_id=user_id)))
