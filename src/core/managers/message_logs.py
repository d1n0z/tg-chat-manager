from typing import List, Optional

from src.core.managers.base import BaseManager, BaseRepository
from src.core.models import Chat, MessageLog


class MessageLogRepository(BaseRepository):
    async def add_message(
        self,
        tg_chat_id: int,
        message_id: int,
        message_thread_id: Optional[int] = None,
        media_group_id: Optional[str] = None,
    ):
        chat, _ = await Chat.get_or_create(tg_chat_id=tg_chat_id)
        log, created = await MessageLog.get_or_create(
            chat_id=chat.id,
            message_id=message_id,
            defaults={
                "message_thread_id": message_thread_id,
                "media_group_id": media_group_id,
            },
        )
        if created:
            return log

        update_fields: list[str] = []
        if (
            message_thread_id is not None
            and log.message_thread_id != message_thread_id
        ):
            log.message_thread_id = message_thread_id
            update_fields.append("message_thread_id")
        if media_group_id is not None and log.media_group_id != media_group_id:
            log.media_group_id = media_group_id
            update_fields.append("media_group_id")
        if update_fields:
            await log.save(update_fields=update_fields)
        return log

    async def get_last_n_messages(
        self, tg_chat_id: int, count: int, message_thread_id: Optional[int] = None
    ) -> List[int]:
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if not chat:
            return []
        query = MessageLog.filter(chat_id=chat.id)
        if message_thread_id is not None:
            query = query.filter(message_thread_id=message_thread_id)
        else:
            query = query.filter(message_thread_id__isnull=True)
        logs = await query.order_by("-created_at").limit(count)
        return [log.message_id for log in logs]

    async def get_media_group_messages(
        self,
        tg_chat_id: int,
        media_group_id: str,
        message_thread_id: Optional[int] = None,
    ) -> List[int]:
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if not chat:
            return []
        query = MessageLog.filter(chat_id=chat.id, media_group_id=media_group_id)
        if message_thread_id is not None:
            query = query.filter(message_thread_id=message_thread_id)
        else:
            query = query.filter(message_thread_id__isnull=True)
        logs = await query.order_by("message_id")
        return [log.message_id for log in logs]

    async def get_message_media_group(
        self, tg_chat_id: int, message_id: int, message_thread_id: Optional[int] = None
    ) -> Optional[str]:
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if not chat:
            return None
        query = MessageLog.filter(chat_id=chat.id, message_id=message_id)
        if message_thread_id is not None:
            query = query.filter(message_thread_id=message_thread_id)
        return getattr(await query.order_by("-created_at").first(), "media_group_id", None)

    async def get_message_log(
        self, tg_chat_id: int, message_id: int
    ) -> Optional[MessageLog]:
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if not chat:
            return None
        return await MessageLog.filter(
            chat_id=chat.id, message_id=message_id
        ).order_by("-created_at").first()


class MessageLogManager(BaseManager):
    def __init__(self):
        super().__init__()
        self.repo = MessageLogRepository(self._lock)

        self.add_message = self.repo.add_message
        self.get_last_n_messages = self.repo.get_last_n_messages
        self.get_media_group_messages = self.repo.get_media_group_messages
        self.get_message_media_group = self.repo.get_message_media_group
        self.get_message_log = self.repo.get_message_log
