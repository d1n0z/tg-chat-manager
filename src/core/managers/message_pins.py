import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, TypeAlias
from tortoise.transactions import in_transaction
from src.core.managers.base import BaseCachedModel, BaseCacheManager, BaseManager, BaseRepository
from src.core.models import MessagePin


@dataclass
class _CachedPin(BaseCachedModel):
    id: Optional[int]
    chat_id: int
    message_id: int
    pinned_by_id: Optional[int]
    pinned_at: Any


CacheKey: TypeAlias = Tuple[int, int]  # (chat_id, message_id)
Cache: TypeAlias = Dict[CacheKey, _CachedPin]


def _make_cache_key(chat_id: int, message_id: int) -> CacheKey:
    return (chat_id, message_id)


class MessagePinRepository(BaseRepository):
    async def ensure_record(self, chat_id: int, message_id: int, pinned_by_id: Optional[int]) -> Tuple[MessagePin, bool]:
        obj, created = await MessagePin.get_or_create(
            chat_id=chat_id,
            message_id=message_id,
            defaults={"pinned_by_id": pinned_by_id},
        )
        return obj, created

    async def delete_record(self, chat_id: int, message_id: int):
        await MessagePin.filter(chat_id=chat_id, message_id=message_id).delete()

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
                key = _make_cache_key(r.chat_id, r.message_id)  # type: ignore
                self._cache[key] = _CachedPin(
                    id=r.id,
                    chat_id=r.chat_id,  # type: ignore
                    message_id=r.message_id,
                    pinned_by_id=r.pinned_by_id,  # type: ignore
                    pinned_at=r.pinned_at,
                )
        await super().initialize()

    async def add_pin(self, chat_id: int, message_id: int, pinned_by_id: Optional[int]):
        model, _ = await self.repo.ensure_record(chat_id, message_id, pinned_by_id)
        key = _make_cache_key(chat_id, message_id)
        async with self._lock:
            self._cache[key] = _CachedPin(
                id=model.id,
                chat_id=model.chat_id,  # type: ignore
                message_id=model.message_id,
                pinned_by_id=model.pinned_by_id,  # type: ignore
                pinned_at=model.pinned_at,
            )
            self._dirty.add(key)

    async def remove_pin(self, chat_id: int, message_id: int):
        key = _make_cache_key(chat_id, message_id)
        async with self._lock:
            self._cache.pop(key, None)
            self._dirty.discard(key)
        await self.repo.delete_record(chat_id, message_id)

    async def get_chat_pins(self, chat_id: int) -> List[_CachedPin]:
        async with self._lock:
            return [copy.deepcopy(v) for (c, _), v in self._cache.items() if c == chat_id]

    async def sync(self, batch_size: int = 500):
        async with self._lock:
            dirty_snapshot = set(self._dirty)
            payloads = {k: copy.deepcopy(self._cache[k]) for k in dirty_snapshot if k in self._cache}
        if not payloads:
            return

        async with in_transaction():
            for k, v in payloads.items():
                await MessagePin.update_or_create(
                    defaults={"pinned_by_id": v.pinned_by_id},
                    chat_id=v.chat_id,
                    message_id=v.message_id,
                )

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
