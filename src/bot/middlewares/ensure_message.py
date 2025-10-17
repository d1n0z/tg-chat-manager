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
        _message = None
        if isinstance(event, CallbackQuery):
            if not event.message or isinstance(event.message, InaccessibleMessage) or not event.bot:
                raise CancelHandler()
            _message = event.message
        if isinstance(event, Message) or _message:
            _to_check = _message or event
            if not _to_check.bot or not _to_check.from_user:
                raise CancelHandler()
        return await handler(event, data)
