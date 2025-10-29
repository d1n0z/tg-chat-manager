from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.dispatcher.event.bases import CancelHandler
from aiogram.types import Update
from aiogram.enums import ChatType

from src.core import managers, enums
from src.bot.types import Message


class SilenceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        if not event.message:
            return await handler(event, data)

        message: Message = event.message  # type: ignore

        if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            return await handler(event, data)

        chat_id = message.chat.id

        setting_key = "silence_chat"
        if message.is_topic_message and getattr(message, "message_thread_id", None):
            setting_key = f"silence_topic:{message.message_thread_id}"

        try:
            is_silenced = await managers.chat_settings.get(chat_id, setting_key)
        except Exception:
            return await handler(event, data)

        if not is_silenced:
            return await handler(event, data)

        from_user = message.from_user
        if not from_user:
            raise CancelHandler()

        try:
            role = (
                await managers.user_roles.get(
                    managers.user_roles.make_cache_key(from_user.id, chat_id),
                    "level",
                )
            ) or enums.Role.user
        except Exception:
            role = enums.Role.user

        if role is not None and role != enums.Role.user:
            return await handler(event, data)

        try:
            await message.delete()
        except Exception:
            try:
                await message.bot.delete_message(chat_id, message.message_id)
            except Exception:
                pass

        raise CancelHandler()
