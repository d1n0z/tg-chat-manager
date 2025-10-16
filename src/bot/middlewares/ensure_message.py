from typing import Any, Awaitable, Callable, Union

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import CancelHandler
from aiogram.types import CallbackQuery, InaccessibleMessage, Message


class EnsureMessageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Union[Message, CallbackQuery], dict[str, Any]], Awaitable[Any]],
        event: Union[Message, CallbackQuery],
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery):
            if not event.message or isinstance(event.message, InaccessibleMessage):
                raise CancelHandler()
        elif isinstance(event, Message):
            if not event.bot or not event.from_user:
                raise CancelHandler()
        return await handler(event, data)
