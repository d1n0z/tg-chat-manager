import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, TypeAlias, Union, overload

from tortoise.transactions import in_transaction

from src.core.managers.base import BaseCachedModel, BaseCacheManager, BaseManager, BaseRepository
from src.core.models import InviteUsage, InviteLink, User


@dataclass
class _CachedInviteUsage(BaseCachedModel):
    id: Optional[int]
    invite_id: int
    user_id: int
    used_at: Any


CacheKey: TypeAlias = Tuple[int, int]  # (invite_id, user_id)
Cache: TypeAlias = Dict[CacheKey, _CachedInviteUsage]


def _make_cache_key(invite_id: int, user_id: int) -> CacheKey:
    return (invite_id, user_id)


class InviteUsageRepository(BaseRepository):
    async def ensure_invite(self, invite_id: int) -> InviteLink:
        return await InviteLink.get(id=invite_id)

    async def ensure_user(self, user_id: int) -> User:
        return await User.get(id=user_id)

    async def ensure_record(
        self,
        invite_id: int,
        user_id: int,
        used_at: Optional[Any] = None
    ) -> Tuple[InviteUsage, bool]:
        defaults = {"used_at": used_at or datetime.now(timezone.utc)}
        invite = await self.ensure_invite(invite_id)
        user = await self.ensure_user(user_id)
        obj, created = await InviteUsage.get_or_create(
            invite_id=invite.id,
            user_id=user.id,
            defaults=defaults,
        )
        return obj, created

    async def delete_record(self, invite_id: int, user_id: int):
        await InviteUsage.filter(invite_id=invite_id, user_id=user_id).delete()

    async def all(self) -> List[InviteUsage]:
        return await InviteUsage.all().prefetch_related("invite", "user")


class InviteUsageCache(BaseCacheManager):
    def __init__(self, lock, repo: InviteUsageRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache: Cache = cache
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for row in rows:
                key = _make_cache_key(row.invite_id, row.user_id)  # type: ignore
                self._cache[key] = _CachedInviteUsage(
                    id=row.id,
                    invite_id=row.invite_id,  # type: ignore
                    user_id=row.user_id,  # type: ignore
                    used_at=row.used_at,
                )
        await super().initialize()

    async def _ensure_cached(self, invite_id: int, user_id: int, used_at: Optional[Any] = None) -> bool:
        key = _make_cache_key(invite_id, user_id)
        async with self._lock:
            if key in self._cache:
                return False

        model, created = await self.repo.ensure_record(invite_id, user_id, used_at)
        async with self._lock:
            self._cache[key] = _CachedInviteUsage(
                id=model.id,
                invite_id=model.invite_id,  # type: ignore
                user_id=model.user_id,  # type: ignore
                used_at=model.used_at,
            )
        return created

    @overload
    async def get(self, cache_key: CacheKey, fields=None) -> Any: ...
    @overload
    async def get(self, cache_key: CacheKey, fields: str) -> Any: ...
    @overload
    async def get(self, cache_key: CacheKey, fields: Sequence[str]) -> Tuple[Any, ...]: ...

    async def get(self, cache_key: CacheKey, fields: Union[None, str, Sequence[str]] = None):
        async with self._lock:
            obj = self._cache.get(cache_key)
        if fields is None:
            return obj
        if isinstance(fields, str):
            return getattr(obj, fields, None) if obj else None
        else:
            return tuple([getattr(obj, f, None) for f in fields]) if obj else tuple([None for _ in fields])

    async def add_usage(self, invite_id: int, user_id: int, used_at: Optional[Any] = None):
        created = await self._ensure_cached(invite_id, user_id, used_at)
        key = _make_cache_key(invite_id, user_id)
        async with self._lock:
            r = self._cache[key]
            r.used_at = used_at
            self._dirty.add(key)
        return created

    async def remove_usage(self, invite_id: int, user_id: int):
        key = _make_cache_key(invite_id, user_id)
        async with self._lock:
            if key in self._cache:
                self._dirty.discard(key)
                del self._cache[key]
        await self.repo.delete_record(invite_id, user_id)

    async def get_invite_usages(self, invite_id: int) -> List[_CachedInviteUsage]:
        async with self._lock:
            return [copy.deepcopy(v) for k, v in self._cache.items() if k[0] == invite_id]

    async def get_user_usages(self, user_id: int) -> List[_CachedInviteUsage]:
        async with self._lock:
            return [copy.deepcopy(v) for k, v in self._cache.items() if k[1] == user_id]

    async def sync(self, batch_size: int = 1000):
        async with self._lock:
            if not self._dirty:
                return
            dirty_snapshot = set(self._dirty)
            payloads = {k: copy.deepcopy(self._cache[k]) for k in dirty_snapshot if k in self._cache}

        if not payloads:
            return

        items = list(payloads.items())
        try:
            invite_ids = {key[0] for key in payloads.keys()}
            existing_rows = await InviteUsage.filter(invite_id__in=list(invite_ids)).prefetch_related("invite", "user")
            existing_map = {(row.invite_id, row.user_id): row for row in existing_rows}  # type: ignore

            to_update = []
            to_create = []

            for key, cached in items:
                if key in existing_map:
                    row = existing_map[key]
                    dirty = False
                    if row.used_at != cached.used_at:
                        row.used_at = cached.used_at
                        dirty = True
                    if dirty:
                        to_update.append(row)
                else:
                    if cached.invite_id is None or cached.user_id is None:
                        continue
                    to_create.append(InviteUsage(
                        invite_id=cached.invite_id,
                        user_id=cached.user_id,
                        used_at=cached.used_at,
                    ))

            async with in_transaction():
                if to_update:
                    await InviteUsage.bulk_update(to_update, fields=["used_at"], batch_size=batch_size)
                if to_create:
                    await InviteUsage.bulk_create(to_create, batch_size=batch_size)
        except Exception:
            from loguru import logger
            logger.exception("InviteUsage sync failed")
            return

        async with self._lock:
            for key in payloads.keys():
                self._dirty.discard(key)


class InviteUsageManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = InviteUsageRepository(self._lock)
        self.cache = InviteUsageCache(self._lock, self.repo, self._cache)

        self.add_usage = self.cache.add_usage
        self.remove_usage = self.cache.remove_usage
        self.get = self.cache.get
        self.get_invite_usages = self.cache.get_invite_usages
        self.get_user_usages = self.cache.get_user_usages
