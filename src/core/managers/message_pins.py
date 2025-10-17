import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, TypeAlias
from tortoise.transactions import in_transaction
from src.core.managers.base import BaseCachedModel, BaseCacheManager, BaseManager, BaseRepository
from src.core.models import Chat, MessagePin, User


@dataclass
class _CachedPin(BaseCachedModel):
    id: Optional[int]
    tg_chat_id: int
    message_id: int
    pinned_by_tg_id: Optional[int]
    pinned_at: Any


CacheKey: TypeAlias = Tuple[int, int]  # (tg_chat_id, message_id)
Cache: TypeAlias = Dict[CacheKey, _CachedPin]


def _make_cache_key(tg_chat_id: int, message_id: int) -> CacheKey:
    return (tg_chat_id, message_id)


class MessagePinRepository(BaseRepository):
    async def ensure_record(self, tg_chat_id: int, message_id: int, pinned_by_tg_id: Optional[int]) -> Tuple[MessagePin, bool]:
        chat, _ = await Chat.get_or_create(tg_chat_id=tg_chat_id)
        pinned_by_id = None
        if pinned_by_tg_id:
            pinned_by, _ = await User.get_or_create(tg_user_id=pinned_by_tg_id)
            pinned_by_id = pinned_by.id
        obj, created = await MessagePin.get_or_create(
            chat_id=chat.id,
            message_id=message_id,
            defaults={"pinned_by_id": pinned_by_id},
        )
        return obj, created

    async def delete_record(self, tg_chat_id: int, message_id: int):
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if chat:
            await MessagePin.filter(chat_id=chat.id, message_id=message_id).delete()

    async def all(self) -> List[MessagePin]:
        return await MessagePin.all().prefetch_related("chat", "pinned_by")


class MessagePinCache(BaseCacheManager):
    def __init__(self, lock, repo: MessagePinRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache = cache
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for r in rows:
                key = _make_cache_key(r.chat.tg_chat_id, r.message_id)  # type: ignore
                self._cache[key] = _CachedPin(
                    id=r.id,
                    tg_chat_id=r.chat.tg_chat_id,  # type: ignore
                    message_id=r.message_id,
                    pinned_by_tg_id=r.pinned_by.tg_user_id if r.pinned_by else None,  # type: ignore
                    pinned_at=r.pinned_at,
                )
        await super().initialize()

    async def add_pin(self, tg_chat_id: int, message_id: int, pinned_by_tg_id: Optional[int]):
        key = _make_cache_key(tg_chat_id, message_id)
        async with self._lock:
            if key in self._cache:
                return
        
        model, _ = await self.repo.ensure_record(tg_chat_id, message_id, pinned_by_tg_id)
        async with self._lock:
            self._cache[key] = _CachedPin(
                id=model.id,
                tg_chat_id=tg_chat_id,
                message_id=model.message_id,
                pinned_by_tg_id=pinned_by_tg_id,
                pinned_at=model.pinned_at,
            )
            self._dirty.add(key)

    async def remove_pin(self, tg_chat_id: int, message_id: int):
        key = _make_cache_key(tg_chat_id, message_id)
        async with self._lock:
            self._cache.pop(key, None)
            self._dirty.discard(key)
        await self.repo.delete_record(tg_chat_id, message_id)

    async def get_chat_pins(self, tg_chat_id: int) -> List[_CachedPin]:
        async with self._lock:
            return [copy.deepcopy(v) for k, v in self._cache.items() if k[0] == tg_chat_id]

    async def sync(self, batch_size: int = 500):
        async with self._lock:
            dirty_snapshot = set(self._dirty)
            payloads = {k: copy.deepcopy(self._cache[k]) for k in dirty_snapshot if k in self._cache}
        if not payloads:
            return

        try:
            tg_chat_ids = {k[0] for k in payloads.keys()}
            chats = await Chat.filter(tg_chat_id__in=list(tg_chat_ids))
            chat_map = {c.tg_chat_id: c.id for c in chats}
            
            async with in_transaction():
                for k, v in payloads.items():
                    tg_chat_id, message_id = k
                    if tg_chat_id not in chat_map:
                        continue
                    pinned_by_id = None
                    if v.pinned_by_tg_id:
                        pinned_by = await User.filter(tg_user_id=v.pinned_by_tg_id).first()
                        if pinned_by:
                            pinned_by_id = pinned_by.id
                    await MessagePin.update_or_create(
                        defaults={"pinned_by_id": pinned_by_id},
                        chat_id=chat_map[tg_chat_id],
                        message_id=message_id,
                    )
        except Exception:
            from loguru import logger
            logger.exception("MessagePin sync failed")
            return

        async with self._lock:
            self._dirty -= dirty_snapshot


class MessagePinManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = MessagePinRepository(self._lock)
        self.cache = MessagePinCache(self._lock, self.repo, self._cache)

        self.add_pin = self.cache.add_pin
        self.remove_pin = self.cache.remove_pin
        self.get_chat_pins = self.cache.get_chat_pins
