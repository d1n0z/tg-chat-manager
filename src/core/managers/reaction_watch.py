from datetime import datetime, timezone
from typing import List

from src.core.managers.base import BaseManager, BaseRepository
from src.core.models import Chat, ReactionWatch


class ReactionWatchRepository(BaseRepository):
    async def add_watch(
        self, tg_chat_id: int, message_id: int, message_thread_id: int | None
    ):
        chat, _ = await Chat.get_or_create(tg_chat_id=tg_chat_id)
        return await ReactionWatch.create(
            chat_id=chat.id,
            message_id=message_id,
            message_thread_id=message_thread_id,
        )

    async def mark_resolved(self, tg_chat_id: int, message_id: int, delete_instead_of_marking: bool = False):
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if not chat:
            return
        row = ReactionWatch.filter(chat_id=chat.id, message_id=message_id)
        if delete_instead_of_marking:
            await row.delete()
            return
        await row.update(resolved=True)

    async def touch_notified(self, watch: ReactionWatch):
        watch.notified_count = (watch.notified_count or 0) + 1
        watch.last_notified_at = datetime.now(timezone.utc)
        await watch.save()

    async def touch_notified_with_count(self, watch: ReactionWatch, set_count: int):
        watch.notified_count = set_count
        watch.last_notified_at = datetime.now(timezone.utc)
        await watch.save()

    async def get_unresolved_watches(self) -> List[ReactionWatch]:
        return await ReactionWatch.filter(resolved=False).prefetch_related("chat")


class ReactionWatchManager(BaseManager):
    def __init__(self):
        super().__init__()
        self.repo = ReactionWatchRepository(self._lock)

    async def add_watch(
        self, tg_chat_id: int, message_id: int, message_thread_id: int | None
    ):
        return await self.repo.add_watch(tg_chat_id, message_id, message_thread_id)

    async def mark_resolved(self, tg_chat_id: int, message_id: int, delete_instead_of_marking: bool = True):
        await self.repo.mark_resolved(tg_chat_id, message_id, delete_instead_of_marking)

    async def touch_notified(self, watch: ReactionWatch):
        await self.repo.touch_notified(watch)

    async def touch_notified_with_count(self, watch: ReactionWatch, set_count: int):
        return await self.repo.touch_notified_with_count(watch, set_count)

    async def get_unresolved_watches(self) -> List[ReactionWatch]:
        return await self.repo.get_unresolved_watches()
