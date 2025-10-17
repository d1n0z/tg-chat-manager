import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, TypeAlias
from tortoise.transactions import in_transaction
from src.core.managers.base import BaseCachedModel, BaseCacheManager, BaseManager, BaseRepository
from src.core.models import Chat, ChatSetting


@dataclass
class _CachedChatSetting(BaseCachedModel):
    id: Optional[int]
    tg_chat_id: int
    key: str
    value: Any


CacheKey: TypeAlias = Tuple[int, str]  # (tg_chat_id, key)
Cache: TypeAlias = Dict[CacheKey, _CachedChatSetting]


def _make_cache_key(tg_chat_id: int, key: str) -> CacheKey:
    return (tg_chat_id, key)


class ChatSettingRepository(BaseRepository):
    async def ensure_record(self, tg_chat_id: int, key: str, value: Any) -> ChatSetting:
        chat, _ = await Chat.get_or_create(tg_chat_id=tg_chat_id)
        obj, _ = await ChatSetting.get_or_create(
            chat_id=chat.id,
            key=key,
            defaults={"value": value},
        )
        if obj.value != value:
            obj.value = value
            await obj.save()
        return obj

    async def delete_record(self, tg_chat_id: int, key: str):
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if chat:
            await ChatSetting.filter(chat_id=chat.id, key=key).delete()

    async def all(self) -> List[ChatSetting]:
        return await ChatSetting.all().prefetch_related("chat")


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
                key = _make_cache_key(r.chat.tg_chat_id, r.key)  # type: ignore
                self._cache[key] = _CachedChatSetting(
                    id=r.id,
                    tg_chat_id=r.chat.tg_chat_id,  # type: ignore
                    key=r.key,
                    value=r.value,
                )
        await super().initialize()

    async def set(self, tg_chat_id: int, key: str, value: Any):
        cache_key = _make_cache_key(tg_chat_id, key)
        async with self._lock:
            if cache_key in self._cache:
                self._cache[cache_key].value = value
                self._dirty.add(cache_key)
                return
        
        record = await self.repo.ensure_record(tg_chat_id, key, value)
        async with self._lock:
            self._cache[cache_key] = _CachedChatSetting(
                id=record.id,
                tg_chat_id=tg_chat_id,
                key=key,
                value=value,
            )
            self._dirty.add(cache_key)

    async def get(self, tg_chat_id: int, key: str) -> Optional[Any]:
        cache_key = _make_cache_key(tg_chat_id, key)
        async with self._lock:
            r = self._cache.get(cache_key)
            return r.value if r else None

    async def remove(self, tg_chat_id: int, key: str):
        cache_key = _make_cache_key(tg_chat_id, key)
        async with self._lock:
            self._cache.pop(cache_key, None)
            self._dirty.discard(cache_key)
        await self.repo.delete_record(tg_chat_id, key)

    async def get_chat_settings(self, tg_chat_id: int) -> List[_CachedChatSetting]:
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
                for key, cached in payloads.items():
                    tg_chat_id, setting_key = key
                    if tg_chat_id not in chat_map:
                        continue
                    await ChatSetting.update_or_create(
                        defaults={"value": cached.value},
                        chat_id=chat_map[tg_chat_id],
                        key=setting_key,
                    )
        except Exception:
            from loguru import logger
            logger.exception("ChatSetting sync failed")
            return

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
