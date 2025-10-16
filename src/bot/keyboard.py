import urllib.parse
from typing import Self, Sequence, Union, overload

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class AutoKeyboard:
    _kb: InlineKeyboardBuilder

    def __new__(cls, *args, **kwargs):
        self = super().__new__(cls)
        self._kb = InlineKeyboardBuilder()
        cls.__init__(self, *args, **kwargs)
        return self._kb.as_markup()

    def add(self, *buttons: InlineKeyboardButton):
        self._kb.add(*buttons)
        return self

    def row(self, *buttons: InlineKeyboardButton):
        if buttons:
            self._kb.row(*buttons)
        else:
            self._kb.row()
        return self

    @overload
    def rows(self, *rows: Sequence[InlineKeyboardButton]) -> Self: ...
    @overload
    def rows(self, *rows: InlineKeyboardButton) -> Self: ...

    def rows(self, *rows: Union[Sequence[InlineKeyboardButton], InlineKeyboardButton]):
        if rows:
            for buttons in rows:
                self._kb.row(
                    *(
                        [buttons]
                        if isinstance(buttons, InlineKeyboardButton)
                        else buttons
                    )
                )
        else:
            self._kb.row()
        return self

    def cb(self, text: str, data: CallbackData | str):
        callback_data = data.pack() if isinstance(data, CallbackData) else data
        return InlineKeyboardButton(text=text, callback_data=callback_data)

    def url(self, text: str, url: str):
        return InlineKeyboardButton(text=text, url=url)

    def as_markup(self) -> InlineKeyboardMarkup:
        return self._kb.as_markup()


class ChatsPaginate(CallbackData, prefix="chats"):
    page: int


class ChatSelect(CallbackData, prefix="chat"):
    chat_id: int


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


class GenerateInvite(CallbackData, prefix="gen_inv"):
    chat_id: int


class chat_card(AutoKeyboard):
    def __init__(self, chat_id: int, invite_url: str | None = None):
        self.row(
            self.cb("Получить новую пригласительную ссылку", GenerateInvite(chat_id=chat_id))
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
