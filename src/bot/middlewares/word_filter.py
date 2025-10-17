from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import CancelHandler
from aiogram.enums import ChatType
from aiogram.types import Update

from src.core import managers


class WordFilterMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        if (
            event.message
            and event.message.text
            and not event.message.text.startswith('/words')
            and event.message.chat.type in (ChatType.SUPERGROUP, ChatType.GROUP)
        ):
            words = await managers.word_filters.get_chat_words(event.message.chat.id)
            if words:
                text_lower = event.message.text.lower()
                for word in words:
                    if word in text_lower:
                        try:
                            await event.message.delete()
                        except Exception:
                            pass
                        raise CancelHandler()
        return await handler(event, data)
