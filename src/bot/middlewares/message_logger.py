from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message, Update

from src.core import managers


class MessageLoggerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        if event.message and event.message.chat.type in (
            ChatType.SUPERGROUP,
            ChatType.GROUP,
        ):
            await managers.message_logs.add_message(
                event.message.chat.id,
                event.message.message_id,
                event.message.message_thread_id,
            )
            if event.message.from_user and not event.message.from_user.is_bot:
                await managers.users.increment_messages_count(event.message.from_user.id)
        result = await handler(event, data)
        if isinstance(result, Message) and result.chat.type in (
            ChatType.SUPERGROUP,
            ChatType.GROUP,
        ):
            await managers.message_logs.add_message(
                result.chat.id,
                result.message_id,
                result.message_thread_id,
            )
        return result
