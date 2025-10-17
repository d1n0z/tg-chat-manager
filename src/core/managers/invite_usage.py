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
    invite_token: str
    tg_user_id: int
    used_at: Any


CacheKey: TypeAlias = Tuple[str, int]  # (invite_token, tg_user_id)
Cache: TypeAlias = Dict[CacheKey, _CachedInviteUsage]


def _make_cache_key(invite_token: str, tg_user_id: int) -> CacheKey:
    return (invite_token, tg_user_id)


class InviteUsageRepository(BaseRepository):
    async def ensure_record(
        self,
        invite_token: str,
        tg_user_id: int,
        used_at: Optional[Any] = None
    ) -> Tuple[InviteUsage, bool]:
        defaults = {"used_at": used_at or datetime.now(timezone.utc)}
        invite = await InviteLink.filter(token=invite_token).first()
        if not invite:
            raise ValueError(f"Invite with token {invite_token} not found")
        user, _ = await User.get_or_create(tg_user_id=tg_user_id)
        obj, created = await InviteUsage.get_or_create(
            invite_id=invite.id,
            user_id=user.id,
            defaults=defaults,
        )
        return obj, created

    async def delete_record(self, invite_token: str, tg_user_id: int):
        invite = await InviteLink.filter(token=invite_token).first()
        user = await User.filter(tg_user_id=tg_user_id).first()
        if invite and user:
            await InviteUsage.filter(invite_id=invite.id, user_id=user.id).delete()

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
                key = _make_cache_key(row.invite.token, row.user.tg_user_id)  # type: ignore
                self._cache[key] = _CachedInviteUsage(
                    id=row.id,
                    invite_token=row.invite.token,  # type: ignore
                    tg_user_id=row.user.tg_user_id,  # type: ignore
                    used_at=row.used_at,
                )
        await super().initialize()

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

    async def add_usage(self, invite_token: str, tg_user_id: int, used_at: Optional[Any] = None):
        key = _make_cache_key(invite_token, tg_user_id)
        async with self._lock:
            if key in self._cache:
                r = self._cache[key]
                r.used_at = used_at
                self._dirty.add(key)
                return False
        
        model, created = await self.repo.ensure_record(invite_token, tg_user_id, used_at)
        async with self._lock:
            self._cache[key] = _CachedInviteUsage(
                id=model.id,
                invite_token=invite_token,
                tg_user_id=tg_user_id,
                used_at=model.used_at,
            )
            self._dirty.add(key)
        return created

    async def remove_usage(self, invite_token: str, tg_user_id: int):
        key = _make_cache_key(invite_token, tg_user_id)
        async with self._lock:
            if key in self._cache:
                self._dirty.discard(key)
                del self._cache[key]
        await self.repo.delete_record(invite_token, tg_user_id)

    async def get_invite_usages(self, invite_token: str) -> List[_CachedInviteUsage]:
        async with self._lock:
            return [copy.deepcopy(v) for k, v in self._cache.items() if k[0] == invite_token]

    async def get_user_usages(self, tg_user_id: int) -> List[_CachedInviteUsage]:
        async with self._lock:
            return [copy.deepcopy(v) for k, v in self._cache.items() if k[1] == tg_user_id]

    async def sync(self, batch_size: int = 1000):
        async with self._lock:
            if not self._dirty:
                return
            dirty_snapshot = set(self._dirty)
            payloads = {k: copy.deepcopy(self._cache[k]) for k in dirty_snapshot if k in self._cache}

        if not payloads:
            return

        try:
            invite_tokens = {k[0] for k in payloads.keys()}
            tg_user_ids = {k[1] for k in payloads.keys()}
            
            invites = await InviteLink.filter(token__in=list(invite_tokens))
            users = await User.filter(tg_user_id__in=list(tg_user_ids))
            invite_map = {i.token: i.id for i in invites}
            user_map = {u.tg_user_id: u.id for u in users}
            
            invite_db_ids = [invite_map[k[0]] for k in payloads.keys() if k[0] in invite_map and k[1] in user_map]
            existing_rows = await InviteUsage.filter(invite_id__in=invite_db_ids).prefetch_related("invite", "user")
            existing_map = {(row.invite.token, row.user.tg_user_id): row for row in existing_rows}  # type: ignore

            to_update = []
            to_create = []

            for key, cached in payloads.items():
                invite_token, tg_user_id = key
                if key in existing_map:
                    row = existing_map[key]
                    dirty = False
                    if row.used_at != cached.used_at:
                        row.used_at = cached.used_at
                        dirty = True
                    if dirty:
                        to_update.append(row)
                else:
                    if invite_token not in invite_map or tg_user_id not in user_map:
                        continue
                    to_create.append(InviteUsage(
                        invite_id=invite_map[invite_token],
                        user_id=user_map[tg_user_id],
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
