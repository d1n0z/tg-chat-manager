from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import CancelHandler
from aiogram.types import InaccessibleMessage, Update


class EnsureMessageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        if event.message:
            if not event.message.bot or not event.message.from_user:
                raise CancelHandler()
        elif event.callback_query:
            if (
                not event.callback_query.message
                or isinstance(event.callback_query.message, InaccessibleMessage)
                or not event.callback_query.bot
            ):
                raise CancelHandler()
        return await handler(event, data)
