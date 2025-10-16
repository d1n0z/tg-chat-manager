import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, TypeAlias
from tortoise.transactions import in_transaction
from src.core.managers.base import BaseCachedModel, BaseCacheManager, BaseManager, BaseRepository
from src.core.models import ChatSetting


@dataclass
class _CachedChatSetting(BaseCachedModel):
    id: Optional[int]
    chat_id: int
    key: str
    value: Any


CacheKey: TypeAlias = Tuple[int, str]  # (chat_id, key)
Cache: TypeAlias = Dict[CacheKey, _CachedChatSetting]


def _make_cache_key(chat_id: int, key: str) -> CacheKey:
    return (chat_id, key)


class ChatSettingRepository(BaseRepository):
    async def ensure_record(self, chat_id: int, key: str, value: Any) -> ChatSetting:
        obj, _ = await ChatSetting.get_or_create(
            chat_id=chat_id,
            key=key,
            defaults={"value": value},
        )
        return obj

    async def delete_record(self, chat_id: int, key: str):
        await ChatSetting.filter(chat_id=chat_id, key=key).delete()

    async def all(self) -> List[ChatSetting]:
        return await ChatSetting.all()


class ChatSettingCache(BaseCacheManager):
    def __init__(self, lock, repo: ChatSettingRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache = cache
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for r in rows:
                key = _make_cache_key(r.chat_id, r.key)  # type: ignore
                self._cache[key] = _CachedChatSetting(
                    id=r.id,
                    chat_id=r.chat_id,  # type: ignore
                    key=r.key,
                    value=r.value,
                )
        await super().initialize()

    async def set(self, chat_id: int, key: str, value: Any):
        record = await self.repo.ensure_record(chat_id, key, value)
        cache_key = _make_cache_key(chat_id, key)
        async with self._lock:
            self._cache[cache_key] = _CachedChatSetting(
                id=record.id,
                chat_id=chat_id,
                key=key,
                value=value,
            )
            self._dirty.add(cache_key)

    async def get(self, chat_id: int, key: str) -> Optional[Any]:
        cache_key = _make_cache_key(chat_id, key)
        async with self._lock:
            r = self._cache.get(cache_key)
            return r.value if r else None

    async def remove(self, chat_id: int, key: str):
        cache_key = _make_cache_key(chat_id, key)
        async with self._lock:
            self._cache.pop(cache_key, None)
            self._dirty.discard(cache_key)
        await self.repo.delete_record(chat_id, key)

    async def get_chat_settings(self, chat_id: int) -> List[_CachedChatSetting]:
        async with self._lock:
            return [copy.deepcopy(v) for (c, _), v in self._cache.items() if c == chat_id]

    async def sync(self, batch_size: int = 500):
        async with self._lock:
            dirty_snapshot = set(self._dirty)
            payloads = {k: copy.deepcopy(self._cache[k]) for k in dirty_snapshot if k in self._cache}
        if not payloads:
            return

        async with in_transaction():
            for key, cached in payloads.items():
                await ChatSetting.update_or_create(
                    defaults={"value": cached.value},
                    chat_id=cached.chat_id,
                    key=cached.key,
                )

        async with self._lock:
            self._dirty -= dirty_snapshot


class ChatSettingManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = ChatSettingRepository(self._lock)
        self.cache = ChatSettingCache(self._lock, self.repo, self._cache)

        self.set = self.cache.set
        self.get = self.cache.get
        self.remove = self.cache.remove
        self.get_chat_settings = self.cache.get_chat_settings
