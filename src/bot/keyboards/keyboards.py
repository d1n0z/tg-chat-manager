import urllib.parse

from src.bot.keyboards.base import MagicKeyboard
from src.bot.keyboards.callbackdata import (
    Activate,
    ChatSelect,
    ChatsPaginate,
    Form,
    GByNickPaginate,
    GenerateInvite,
    NickListPaginate,
    UnmuteAction,
    UserStats,
)


class start(MagicKeyboard):
    def __init__(self, user_in_massform_chat):
        self.row(self.cb("Все чаты", "all_chats"))
        if user_in_massform_chat:
            self.row(self.cb("Массовые формы", "mass_form_hint"))
            self.row(self.cb("Аналитика IP", "ip_analytics_hint"))
        self.row(self.cb("Помощь", "command_help"))


class chats_paginate(MagicKeyboard):
    def __init__(self, chats: list[tuple[int, str]], page: int = 0, maxpage: int = 0):
        for i in chats:
            self.row(self.cb(i[1], ChatSelect(chat_id=i[0])))

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


class chat_card(MagicKeyboard):
    def __init__(
        self,
        chat_id: int,
        invite_url: str | None = None,
        infinite_invite_url: str | None = None,
    ):
        if infinite_invite_url:
            self.row(
                self.url(
                    "Перейти в чат",
                    infinite_invite_url,
                )
            )
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


class help(MagicKeyboard):
    def __init__(self):
        self.row(self.cb("Назад", "start"))


class nick_list_paginate(MagicKeyboard):
    def __init__(self, page: int, maxpage: int, chat_id: int, no_nick_mode: bool):
        self.row(
            self.cb(
                "С никами" if no_nick_mode else "Без ников",
                NickListPaginate(
                    chat_id=chat_id, page=0, no_nick_mode=not no_nick_mode
                ),
            )
        )
        row = []
        if page > 0:
            row.append(
                self.cb(
                    "Назад",
                    NickListPaginate(
                        chat_id=chat_id, page=page - 1, no_nick_mode=no_nick_mode
                    ),
                )
            )
        if maxpage > 0:
            row.append(
                self.cb(
                    f"[{page + 1}/{maxpage + 1}]",
                    NickListPaginate(
                        chat_id=chat_id, page=page, no_nick_mode=no_nick_mode
                    ),
                )
            )
        if page < maxpage:
            row.append(
                self.cb(
                    "Вперёд",
                    NickListPaginate(
                        chat_id=chat_id, page=page + 1, no_nick_mode=no_nick_mode
                    ),
                )
            )
        if row:
            self.row(*row)


class mute_actions(MagicKeyboard):
    def __init__(self, user_id: int, now_mute: bool):
        # if not now_mute:
        #     self.row(
        #         self.cb("🔇 Мут 1ч", MuteAction(user_id=user_id, duration="1h")),
        #         self.cb("🔇 Мут 6ч", MuteAction(user_id=user_id, duration="6h")),
        #         self.cb("🔇 Мут 24ч", MuteAction(user_id=user_id, duration="24h")),
        #     )
        # else:
        if now_mute:
            self.row(self.cb("🔊 Снять мут", UnmuteAction(user_id=user_id)))


class gbynick_paginate(MagicKeyboard):
    def __init__(self, page: int, maxpage: int, chat_id: int, nick: str):
        row = []
        if page > 0:
            row.append(
                self.cb(
                    "Назад", GByNickPaginate(chat_id=chat_id, nick=nick, page=page - 1)
                )
            )
        if maxpage > 0:
            row.append(
                self.cb(
                    f"[{page + 1}/{maxpage + 1}]",
                    GByNickPaginate(chat_id=chat_id, nick=nick, page=page),
                )
            )
        if page < maxpage:
            row.append(
                self.cb(
                    "Вперёд", GByNickPaginate(chat_id=chat_id, nick=nick, page=page + 1)
                )
            )
        if row:
            self.row(*row)


class activate(MagicKeyboard):
    def __init__(self):
        self.row(self.cb("Активировать", Activate()))


class join(MagicKeyboard):
    def __init__(self, url):
        self.row(self.url("Открыть чат", url))


class user_stats(MagicKeyboard):
    def __init__(self, user_id: int, set_role: bool = False):
        self.row(
            self.cb("Исключить", UserStats(user_id=user_id, button="kick")),
            self.cb("Заблокировать", UserStats(user_id=user_id, button="ban")),
        )
        self.row(
            self.cb("Изменить ник", UserStats(user_id=user_id, button="nick")),
            self.cb("Выдать права", UserStats(user_id=user_id, button="access")),
        )
        if set_role:
            self.row(
                self.cb(
                    "Модератор",
                    UserStats(
                        user_id=user_id, button="set_access", access_key="moderator"
                    ),
                ),
                self.cb(
                    "Старший Модератор",
                    UserStats(
                        user_id=user_id,
                        button="set_access",
                        access_key="senior_moderator",
                    ),
                ),
                self.cb(
                    "Администратор",
                    UserStats(user_id=user_id, button="set_access", access_key="admin"),
                ),
            )


class form(MagicKeyboard):
    def __init__(self):
        self.row(
            self.cb("Принять", Form(accept=True)),
            self.cb("Отказать", Form(accept=False)),
        )
