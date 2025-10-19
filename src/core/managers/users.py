import copy
from dataclasses import dataclass
from datetime import datetime
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

from src.core.config import settings
from src.core.managers.base import (
    BaseCachedModel,
    BaseCacheManager,
    BaseManager,
    BaseRepository,
)
from src.core.models import User


@dataclass
class _CachedUser(BaseCachedModel):
    id: Optional[int]
    tg_user_id: int
    username: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    is_bot: bool
    is_owner: bool
    banned_until: Optional[datetime]
    messages_count: int
    meta: Optional[dict]
    created_at: Any
    last_seen: Optional[Any]


CacheKey: TypeAlias = int  # tg_user_id
Cache: TypeAlias = Dict[CacheKey, _CachedUser]
DbIdIndex: TypeAlias = Dict[int, int]  # db_id -> tg_user_id


DEFAULT_USER = {
    "username": None,
    "first_name": None,
    "last_name": None,
    "is_bot": False,
    "is_owner": False,
    "banned_until": None,
    "messages_count": 0,
    "meta": None,
    "last_seen": None,
}


def _make_cache_key(tg_user_id: int) -> CacheKey:
    return tg_user_id


class UserRepository(BaseRepository):
    async def ensure_record(
        self, tg_user_id: int, defaults: Optional[Dict[str, Any]] = None
    ) -> Tuple[User, bool]:
        defaults = defaults or {}
        safe_defaults = {
            k: v for k, v in DEFAULT_USER.items() if k not in {"tg_user_id"}
        }
        merged_defaults = {**safe_defaults, **defaults}
        obj, created = await User.get_or_create(
            tg_user_id=tg_user_id, defaults=merged_defaults
        )
        return obj, created

    async def get_record_by_tg(self, tg_user_id: int) -> Optional[User]:
        return await User.filter(tg_user_id=tg_user_id).first()

    async def get_all(self) -> List[User]:
        return await User.all()

    async def delete_record_by_tg(self, tg_user_id: int):
        await User.filter(tg_user_id=tg_user_id).delete()


class UserCache(BaseCacheManager):
    def __init__(self, lock, repo: UserRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache: Cache = cache
        self._db_id_index: DbIdIndex = {}
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.get_all()
        async with self._lock:
            for row in rows:
                key = _make_cache_key(row.tg_user_id)
                self._cache[key] = _CachedUser(
                    id=row.id,
                    tg_user_id=row.tg_user_id,
                    username=row.username,
                    first_name=row.first_name,
                    last_name=row.last_name,
                    is_bot=row.is_bot,
                    is_owner=row.is_owner,
                    banned_until=row.banned_until,
                    messages_count=row.messages_count,
                    meta=row.meta,
                    created_at=row.created_at,
                    last_seen=row.last_seen,
                )
                if row.id:
                    self._db_id_index[row.id] = row.tg_user_id
        await super().initialize()

    async def _ensure_cached(
        self, tg_user_id: int, initial_data: Optional[Dict[str, Any]] = None
    ):
        async with self._lock:
            if tg_user_id in self._cache:
                return self._cache[tg_user_id]

        defaults = initial_data or {}
        model, _ = await self.repo.ensure_record(tg_user_id, defaults=defaults)
        async with self._lock:
            self._cache[tg_user_id] = _CachedUser(
                id=model.id,
                tg_user_id=model.tg_user_id,
                username=model.username,
                first_name=model.first_name,
                last_name=model.last_name,
                is_bot=model.is_bot,
                is_owner=model.is_owner,
                banned_until=model.banned_until,
                messages_count=model.messages_count,
                meta=model.meta,
                created_at=model.created_at,
                last_seen=model.last_seen,
            )
            if model.id:
                self._db_id_index[model.id] = model.tg_user_id
        return model

    @overload
    async def get(self, cache_key: CacheKey, fields: None = None) -> Any: ...
    @overload
    async def get(self, cache_key: CacheKey, fields: str) -> Any: ...
    @overload
    async def get(
        self, cache_key: CacheKey, fields: Sequence[str]
    ) -> Tuple[Any, ...]: ...

    async def get(
        self, cache_key: CacheKey, fields: Union[None, str, Sequence[str]] = None
    ):
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
                cached = self._cache[cache_key]
                if cached.id:
                    self._db_id_index.pop(cached.id, None)
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

                existing_rows = await User.filter(tg_user_id__in=tg_ids)
                existing_map = {row.tg_user_id: row for row in existing_rows}

                to_update = []
                to_create = []
                for tg, cached in batch:
                    if tg in existing_map:
                        row = existing_map[tg]
                        dirty = False
                        for field in (
                            "username",
                            "first_name",
                            "last_name",
                            "is_bot",
                            "is_owner",
                            "banned_until",
                            "messages_count",
                            "meta",
                            "last_seen",
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
                            User(
                                tg_user_id=cached.tg_user_id,
                                username=cached.username,
                                first_name=cached.first_name,
                                last_name=cached.last_name,
                                is_bot=cached.is_bot,
                                is_owner=cached.is_owner,
                                banned_until=cached.banned_until,
                                messages_count=cached.messages_count,
                                meta=cached.meta,
                                last_seen=cached.last_seen,
                            )
                        )

                if to_update:
                    await User.bulk_update(
                        to_update,
                        fields=[
                            "username",
                            "first_name",
                            "last_name",
                            "is_bot",
                            "is_owner",
                            "banned_until",
                            "messages_count",
                            "meta",
                            "last_seen",
                        ],
                        batch_size=batch_size,
                    )
                if to_create:
                    await User.bulk_create(to_create, batch_size=batch_size)

        except Exception:
            from loguru import logger

            logger.exception("User sync failed")
            return

        async with self._lock:
            for tg, old_val in payloads.items():
                cur = self._cache.get(tg)
                if cur is None:
                    self._dirty.discard(tg)
                    continue
                if cur.__dict__ == old_val.__dict__:
                    self._dirty.discard(tg)
                    
    async def increment_messages_count(self, cache_key: CacheKey) -> bool:
        async with self._lock:
            obj = self._cache.get(cache_key)
            if not obj:
                return False
            obj.messages_count += 1
            self._dirty.add(cache_key)
            return True


class UserManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = UserRepository(self._lock)
        self.cache = UserCache(self._lock, self.repo, self._cache)

        self.get = self.cache.get
        self.edit = self.cache.edit
        self.remove = self.cache.remove
        self.ensure_user = self.cache._ensure_cached
        self.increment_messages_count = self.cache.increment_messages_count

    async def get_name(self, tg_user_id: int) -> Optional[str]:
        first, last = await self.cache.get(tg_user_id, ("first_name", "last_name"))
        if first is None and last is None:
            return None
        return (" ".join([p for p in (first, last) if p])).strip()
    


    async def get_by_username(self, tg_username: str) -> Optional[_CachedUser]:
        async with self._lock:
            for user in self._cache.values():
                if user.username == tg_username:
                    return copy.deepcopy(user)

    async def set_last_seen(self, tg_user_id: int, last_seen):
        await self.cache.edit(tg_user_id, last_seen=last_seen)

    async def set_meta(self, tg_user_id: int, meta: dict):
        await self.cache.edit(tg_user_id, meta=meta)

    async def mark_bot(self, tg_user_id: int, is_bot: bool = True):
        await self.cache.edit(tg_user_id, is_bot=is_bot)

    async def set_owner(self, tg_user_id: int, is_owner: bool = True):
        await self.cache.edit(tg_user_id, is_owner=is_owner)

    async def is_owner(self, tg_user_id: int) -> bool:
        is_owner = await self.cache.get(tg_user_id, "is_owner")
        if not is_owner and tg_user_id in settings.OWNER_TELEGRAM_IDS:
            await self.set_owner(tg_user_id, True)
            return True
        return is_owner or False
