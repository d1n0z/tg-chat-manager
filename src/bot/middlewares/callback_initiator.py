from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Update


class CallbackInitiatorMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        if event.callback_query and event.callback_query.data:
            parts = event.callback_query.data.split(':')
            if len(parts) > 1:
                try:
                    initiator_id = int(parts[1])
                    if event.callback_query.from_user.id != initiator_id:
                        await event.callback_query.answer()
                        return
                except (ValueError, IndexError):
                    pass
        return await handler(event, data)
