from typing import Self, Sequence, Union, overload

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class MagicKeyboard:
    _kb: InlineKeyboardBuilder
    _initiator_id: int

    def __new__(cls, initiator_id: int, *args, **kwargs):
        self = super().__new__(cls)
        self._kb = InlineKeyboardBuilder()
        self._initiator_id = initiator_id
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
        if isinstance(data, CallbackData) and hasattr(data, "initiator_id"):
            data.initiator_id = self._initiator_id  # type: ignore
        callback_data = data.pack() if isinstance(data, CallbackData) else data
        return InlineKeyboardButton(text=text, callback_data=callback_data)

    def url(self, text: str, url: str):
        return InlineKeyboardButton(text=text, url=url)

    def as_markup(self) -> InlineKeyboardMarkup:
        return self._kb.as_markup()
