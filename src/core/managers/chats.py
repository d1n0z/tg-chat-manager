import copy
from dataclasses import dataclass
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeAlias,
    Union,
    overload,
)

from src.core.managers.base import (
    BaseCachedModel,
    BaseCacheManager,
    BaseManager,
    BaseRepository,
)
from src.core.models import Chat


@dataclass
class _CachedChat(BaseCachedModel):
    id: Optional[int]
    tg_chat_id: int
    title: Optional[str]
    username: Optional[str]
    chat_type: Optional[str]
    cluster_id: Optional[int]
    is_active: bool
    infinite_invite_link: Optional[str]
    settings: Optional[dict]
    created_at: Any


CacheKey: TypeAlias = int  # tg_chat_id
Cache: TypeAlias = Dict[CacheKey, _CachedChat]


DEFAULT_CHAT = {
    "title": None,
    "username": None,
    "chat_type": None,
    "cluster_id": None,
    "is_active": True,
    "infinite_invite_link": None,
    "settings": None,
}


def _make_cache_key(tg_chat_id: int) -> CacheKey:
    return tg_chat_id


class ChatRepository(BaseRepository):
    async def ensure_record(
        self, tg_chat_id: int, defaults: Optional[Dict[str, Any]] = None
    ) -> Tuple[Chat, bool]:
        defaults = defaults or {}
        safe_defaults = {
            k: v for k, v in DEFAULT_CHAT.items() if k not in {"tg_chat_id"}
        }
        merged_defaults = {**safe_defaults, **defaults}
        obj, created = await Chat.get_or_create(
            tg_chat_id=tg_chat_id, defaults=merged_defaults
        )
        return obj, created

    async def get_record_by_tg(self, tg_chat_id: int) -> Optional[Chat]:
        return await Chat.filter(tg_chat_id=tg_chat_id).first()

    async def get_all(self) -> List[Chat]:
        return await Chat.all()

    async def delete_record_by_tg(self, tg_chat_id: int):
        await Chat.filter(tg_chat_id=tg_chat_id).delete()


class ChatCache(BaseCacheManager):
    def __init__(self, lock, repo: ChatRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache: Cache = cache
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.get_all()
        async with self._lock:
            for row in rows:
                key = _make_cache_key(row.tg_chat_id)
                self._cache[key] = _CachedChat(
                    id=row.id,
                    tg_chat_id=row.tg_chat_id,
                    title=row.title,
                    username=row.username,
                    chat_type=row.chat_type,
                    cluster_id=(row.cluster_id if hasattr(row, "cluster_id") else None),  # type: ignore
                    is_active=row.is_active,
                    infinite_invite_link=row.infinite_invite_link,
                    settings=row.settings,
                    created_at=row.created_at,
                )
        await super().initialize()

    async def _ensure_cached(
        self, tg_chat_id: int, initial_data: Optional[Dict[str, Any]] = None
    ) -> _CachedChat | Chat:
        async with self._lock:
            if tg_chat_id in self._cache:
                return self._cache[tg_chat_id]

        defaults = initial_data or {}
        model, created = await self.repo.ensure_record(tg_chat_id, defaults=defaults)
        async with self._lock:
            self._cache[tg_chat_id] = _CachedChat(
                id=model.id,
                tg_chat_id=model.tg_chat_id,
                title=model.title,
                username=model.username,
                chat_type=model.chat_type,
                cluster_id=(model.cluster_id if hasattr(model, "cluster_id") else None),  # type: ignore
                is_active=model.is_active,
                infinite_invite_link=model.infinite_invite_link,
                settings=model.settings,
                created_at=model.created_at,
            )
        return model

    @overload
    async def get(self, cache_key: CacheKey, fields: str) -> Any: ...
    @overload
    async def get(
        self, cache_key: CacheKey, fields: Sequence[str]
    ) -> Tuple[Any, ...]: ...

    async def get(self, cache_key: CacheKey, fields: Union[str, Sequence[str]]):
        async with self._lock:
            obj = self._cache.get(cache_key)

        if fields is None:
            return obj
        if isinstance(fields, str):
            if obj is None:
                return None
            return getattr(obj, fields, None)
        else:
            if obj is None:
                return tuple([None for _ in fields])
            return tuple([getattr(obj, f, None) for f in fields])

    async def edit(self, cache_key: CacheKey, **fields):
        await self._ensure_cached(cache_key, initial_data=fields)
        async with self._lock:
            cached = self._cache.get(cache_key)
            if cached is None:
                return
            for field, value in fields.items():
                if hasattr(cached, field):
                    setattr(cached, field, value)
            self._dirty.add(cache_key)

    async def remove(self, cache_key: CacheKey):
        async with self._lock:
            if cache_key in self._cache:
                self._dirty.discard(cache_key)
                del self._cache[cache_key]
        await self.repo.delete_record_by_tg(cache_key)

    async def sync(self, batch_size: int = 1000):
        async with self._lock:
            if not self._dirty:
                return
            dirty_snapshot = set(self._dirty)
            payloads = {
                tg: copy.deepcopy(self._cache[tg])
                for tg in dirty_snapshot
                if tg in self._cache
            }

        if not payloads:
            return

        items = list(payloads.items())
        try:
            for i in range(0, len(items), batch_size):
                batch = items[i : i + batch_size]
                tg_ids = [tg for tg, _ in batch]

                existing_rows = await Chat.filter(tg_chat_id__in=tg_ids)
                existing_map = {row.tg_chat_id: row for row in existing_rows}

                to_update = []
                to_create = []
                for tg, cached in batch:
                    if tg in existing_map:
                        row = existing_map[tg]
                        dirty = False
                        for field in (
                            "title",
                            "username",
                            "chat_type",
                            "cluster_id",
                            "is_active",
                            "infinite_invite_link",
                            "settings",
                        ):
                            val = getattr(cached, field)
                            row_val = getattr(
                                row, field, getattr(row, f"{field}", None)
                            )
                            if row_val != val:
                                setattr(row, field, val)
                                dirty = True
                        if dirty:
                            to_update.append(row)
                    else:
                        to_create.append(
                            Chat(
                                tg_chat_id=cached.tg_chat_id,
                                title=cached.title,
                                username=cached.username,
                                chat_type=cached.chat_type,
                                cluster_id=cached.cluster_id,
                                is_active=cached.is_active,
                                settings=cached.settings,
                            )
                        )

                if to_update:
                    await Chat.bulk_update(
                        to_update,
                        fields=[
                            "title",
                            "username",
                            "chat_type",
                            "cluster_id",
                            "is_active",
                            "infinite_invite_link",
                            "settings",
                        ],
                        batch_size=batch_size,
                    )
                if to_create:
                    await Chat.bulk_create(to_create, batch_size=batch_size)

        except Exception as e:
            from loguru import logger

            logger.exception("Chat sync failed: {}", e)
            return

        async with self._lock:
            for tg, old_val in payloads.items():
                cur = self._cache.get(tg)
                if cur is None:
                    self._dirty.discard(tg)
                    continue
                if cur.__dict__ == old_val.__dict__:
                    self._dirty.discard(tg)


class ChatManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = ChatRepository(self._lock)
        self.cache = ChatCache(self._lock, self.repo, self._cache)

        self.get = self.cache.get
        self.edit = self.cache.edit
        self.remove = self.cache.remove
        self.ensure_chat = self.cache._ensure_cached

    async def get_full(self, tg_chat_id: int) -> Optional[_CachedChat]:
        async with self._lock:
            return self._cache.get(tg_chat_id, None)

    async def get_settings(self, tg_chat_id: int):
        return await self.cache.get(tg_chat_id, "settings")

    async def set_settings(self, tg_chat_id: int, settings: dict):
        await self.cache.edit(tg_chat_id, settings=settings)

    async def activate(self, tg_chat_id: int):
        await self.cache.edit(tg_chat_id, is_active=True)

    async def deactivate(self, tg_chat_id: int):
        await self.cache.edit(tg_chat_id, is_active=False)
