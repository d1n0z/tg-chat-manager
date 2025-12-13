from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message, Update
from loguru import logger

from src.core import managers
from src.core.config import settings


class MessageLoggerMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        if event.message:
            chat = event.message.chat
        elif event.message_reaction:
            chat = event.message_reaction.chat
        else:
            chat = None

        if chat and chat.type in (
            ChatType.SUPERGROUP,
            ChatType.GROUP,
        ):
            if (
                event.message_reaction
                and getattr(settings, "REACTION_MONITOR_CHAT_ID", None)
                and chat.id == settings.REACTION_MONITOR_CHAT_ID
            ):
                message_id = event.message_reaction.message_id
                if media_group := await managers.message_logs.get_message_media_group(
                    chat.id, message_id
                ):
                    if (
                        media_group_messages
                        := await managers.message_logs.get_media_group_messages(
                            chat.id, media_group
                        )
                    ):
                        for message in media_group_messages:
                            try:
                                await managers.reaction_watches.mark_resolved(
                                    chat.id, message
                                )
                            except Exception:
                                pass
                        return
                try:
                    await managers.reaction_watches.mark_resolved(chat.id, message_id)
                except Exception:
                    logger.exception("Failed to mark reaction resolved:")
                return

            if event.message:
                if event.message.from_user:
                    await managers.user_roles.chat_activation(
                        event.message.from_user.id, chat.id
                    )
                await managers.message_logs.add_message(
                    chat.id, event.message.message_id, event.message.message_thread_id
                )
                try:
                    if (
                        getattr(settings, "REACTION_MONITOR_CHAT_ID", None)
                        and getattr(settings, "REACTION_MONITOR_TOPIC_ID", None)
                        and chat.id == settings.REACTION_MONITOR_CHAT_ID
                        and event.message.message_thread_id
                        == settings.REACTION_MONITOR_TOPIC_ID
                        and event.message.from_user
                        and not event.message.from_user.is_bot
                    ):
                        await managers.reaction_watches.add_watch(
                            chat.id,
                            event.message.message_id,
                            event.message.message_thread_id,
                        )
                except Exception:
                    pass
                if event.message.from_user and not event.message.from_user.is_bot:
                    await managers.users.increment_messages_count(
                        event.message.from_user.id
                    )
        result = await handler(event, data)
        if isinstance(result, Message) and result.chat.type in (
            ChatType.SUPERGROUP,
            ChatType.GROUP,
        ):
            await managers.message_logs.add_message(
                result.chat.id,
                result.message_id,
                result.message_thread_id,
                result.media_group_id,
            )
        return result
