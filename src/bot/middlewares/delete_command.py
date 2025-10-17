from typing import Any, Awaitable, Callable
from unittest.mock import sentinel

from aiogram import BaseMiddleware
from aiogram.types import Update


class DeleteCommandMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)
        if result != sentinel.UNHANDLED and event.message:
            try:
                await event.message.delete()
            except Exception:
                pass
        return result
