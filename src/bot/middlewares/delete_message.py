from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message


class DeleteMessageMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)
        if isinstance(event, Message):
            try:
                await event.delete()
            except Exception:
                pass
        return result
