from typing import List, Optional

from src.core.managers.base import BaseManager, BaseRepository
from src.core.models import Chat, MessageLog


class MessageLogRepository(BaseRepository):
    async def add_message(
        self, tg_chat_id: int, message_id: int, message_thread_id: Optional[int]
    ):
        chat, _ = await Chat.get_or_create(tg_chat_id=tg_chat_id)
        await MessageLog.create(
            chat_id=chat.id, message_id=message_id, message_thread_id=message_thread_id
        )

    async def get_last_n_messages(
        self, tg_chat_id: int, count: int, message_thread_id: Optional[int]
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


class MessageLogManager(BaseManager):
    def __init__(self):
        super().__init__()
        self.repo = MessageLogRepository(self._lock)

    async def add_message(
        self, tg_chat_id: int, message_id: int, message_thread_id: Optional[int] = None
    ):
        await self.repo.add_message(tg_chat_id, message_id, message_thread_id)

    async def get_last_n_messages(
        self, tg_chat_id: int, count: int, message_thread_id: Optional[int] = None
    ) -> List[int]:
        return await self.repo.get_last_n_messages(tg_chat_id, count, message_thread_id)
