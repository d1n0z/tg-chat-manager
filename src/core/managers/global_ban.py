import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, TypeAlias

from tortoise.transactions import in_transaction

from src.core.managers.base import (
    BaseCachedModel,
    BaseCacheManager,
    BaseManager,
    BaseRepository,
)
from src.core.models import Cluster, GlobalBan, User


@dataclass
class _CachedGlobalBan(BaseCachedModel):
    id: Optional[int]
    tg_user_id: int
    cluster_id: Optional[int]
    reason: Optional[str]
    created_by_tg_id: Optional[int]
    created_at: Any
    active: bool
    lifted_by_tg_id: Optional[int]
    lifted_at: Optional[Any]


CacheKey: TypeAlias = Tuple[int, Optional[int]]  # (tg_user_id, cluster_id)
Cache: TypeAlias = Dict[CacheKey, _CachedGlobalBan]


def _make_cache_key(tg_user_id: int, cluster_id: Optional[int]) -> CacheKey:
    return (tg_user_id, cluster_id)


class GlobalBanRepository(BaseRepository):
    async def ensure_record(
        self, tg_user_id: int, cluster_id: Optional[int], **fields
    ) -> Tuple[GlobalBan, bool]:
        user, _ = await User.get_or_create(tg_user_id=tg_user_id)
        created_by_id = None
        if "created_by_tg_id" in fields:
            created_by_tg_id = fields.pop("created_by_tg_id")
            if created_by_tg_id:
                created_by, _ = await User.get_or_create(tg_user_id=created_by_tg_id)
                created_by_id = created_by.id
        lifted_by_id = None
        if "lifted_by_tg_id" in fields:
            lifted_by_tg_id = fields.pop("lifted_by_tg_id")
            if lifted_by_tg_id:
                lifted_by, _ = await User.get_or_create(tg_user_id=lifted_by_tg_id)
                lifted_by_id = lifted_by.id
        return await GlobalBan.get_or_create(
            user_id=user.id, cluster_id=cluster_id, defaults={**fields, "created_by_id": created_by_id, "lifted_by_id": lifted_by_id}
        )

    async def delete_record(self, tg_user_id: int, cluster_id: Optional[int]):
        user = await User.filter(tg_user_id=tg_user_id).first()
        if user:
            await GlobalBan.filter(user_id=user.id, cluster_id=cluster_id).delete()

    async def all(self) -> List[GlobalBan]:
        return await GlobalBan.all().prefetch_related("user", "cluster", "created_by", "lifted_by")


class GlobalBanCache(BaseCacheManager):
    def __init__(self, lock, repo: GlobalBanRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache = cache
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for r in rows:
                key = _make_cache_key(r.user.tg_user_id, r.cluster_id)  # type: ignore
                self._cache[key] = _CachedGlobalBan(
                    id=r.id,
                    tg_user_id=r.user.tg_user_id,  # type: ignore
                    cluster_id=r.cluster_id,  # type: ignore
                    reason=r.reason,
                    created_by_tg_id=r.created_by.tg_user_id if r.created_by else None,  # type: ignore
                    created_at=r.created_at,
                    active=r.active,
                    lifted_by_tg_id=r.lifted_by.tg_user_id if r.lifted_by else None,  # type: ignore
                    lifted_at=r.lifted_at,
                )
        await super().initialize()

    async def add_ban(self, tg_user_id: int, cluster_id: Optional[int], **fields):
        key = _make_cache_key(tg_user_id, cluster_id)
        async with self._lock:
            if key in self._cache:
                r = self._cache[key]
                for k, v in fields.items():
                    if hasattr(r, k):
                        setattr(r, k, v)
                self._dirty.add(key)
                return
        
        model, _ = await self.repo.ensure_record(tg_user_id, cluster_id, **fields)
        async with self._lock:
            self._cache[key] = _CachedGlobalBan(
                id=model.id,
                tg_user_id=tg_user_id,
                cluster_id=model.cluster_id,  # type: ignore
                reason=model.reason,
                created_by_tg_id=fields.get("created_by_tg_id"),
                created_at=model.created_at,
                active=model.active,
                lifted_by_tg_id=fields.get("lifted_by_tg_id"),
                lifted_at=model.lifted_at,
            )
            self._dirty.add(key)

    async def remove_ban(self, tg_user_id: int, cluster_id: Optional[int]):
        key = _make_cache_key(tg_user_id, cluster_id)
        async with self._lock:
            self._cache.pop(key, None)
            self._dirty.discard(key)
        await self.repo.delete_record(tg_user_id, cluster_id)

    async def get_cluster_bans(
        self, cluster_id: Optional[int]
    ) -> List[_CachedGlobalBan]:
        async with self._lock:
            return [
                copy.deepcopy(v)
                for k, v in self._cache.items()
                if k[1] == cluster_id
            ]

    async def get_user_bans(self, tg_user_id: int) -> List[_CachedGlobalBan]:
        async with self._lock:
            return [
                copy.deepcopy(v)
                for k, v in self._cache.items()
                if k[0] == tg_user_id
            ]

    async def sync(self, batch_size: int = 1000):
        async with self._lock:
            dirty_snapshot = set(self._dirty)
            payloads = {
                k: copy.deepcopy(self._cache[k])
                for k in dirty_snapshot
                if k in self._cache
            }
        if not payloads:
            return

        try:
            tg_user_ids = {k[0] for k in payloads.keys()}
            users = await User.filter(tg_user_id__in=list(tg_user_ids))
            user_map = {u.tg_user_id: u.id for u in users}
            
            async with in_transaction():
                for k, v in payloads.items():
                    tg_user_id, cluster_id = k
                    if tg_user_id not in user_map:
                        continue
                    created_by_id = None
                    if v.created_by_tg_id:
                        cb_user = await User.filter(tg_user_id=v.created_by_tg_id).first()
                        if cb_user:
                            created_by_id = cb_user.id
                    lifted_by_id = None
                    if v.lifted_by_tg_id:
                        lb_user = await User.filter(tg_user_id=v.lifted_by_tg_id).first()
                        if lb_user:
                            lifted_by_id = lb_user.id
                    await GlobalBan.update_or_create(
                        defaults=dict(
                            reason=v.reason,
                            created_by_id=created_by_id,
                            active=v.active,
                            lifted_by_id=lifted_by_id,
                            lifted_at=v.lifted_at,
                        ),
                        user_id=user_map[tg_user_id],
                        cluster_id=cluster_id,
                    )
        except Exception:
            from loguru import logger
            logger.exception("GlobalBan sync failed")
            return

        async with self._lock:
            self._dirty -= dirty_snapshot


class GlobalBanManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = GlobalBanRepository(self._lock)
        self.cache = GlobalBanCache(self._lock, self.repo, self._cache)

        self.add_ban = self.cache.add_ban
        self.remove_ban = self.cache.remove_ban
        self.get_cluster_bans = self.cache.get_cluster_bans
        self.get_user_bans = self.cache.get_user_bans
