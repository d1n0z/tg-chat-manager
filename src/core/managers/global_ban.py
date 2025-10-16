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
    user_id: int
    cluster_id: Optional[int]
    reason: Optional[str]
    created_by_id: Optional[int]
    created_at: Any
    active: bool
    lifted_by_id: Optional[int]
    lifted_at: Optional[Any]


CacheKey: TypeAlias = Tuple[int, Optional[int]]
Cache: TypeAlias = Dict[CacheKey, _CachedGlobalBan]


def _make_cache_key(user_id: int, cluster_id: Optional[int]) -> CacheKey:
    return (user_id, cluster_id)


class GlobalBanRepository(BaseRepository):
    async def ensure_user(self, tg_user_id: int) -> Tuple[User, bool]:
        return await User.get_or_create(tg_user_id=tg_user_id, defaults={})

    async def ensure_cluster(self, cluster_id: Optional[int]) -> Optional[Cluster]:
        if cluster_id is None:
            return None
        return await Cluster.get(id=cluster_id)

    async def ensure_record(
        self, user_id: int, cluster_id: Optional[int], **fields
    ) -> Tuple[GlobalBan, bool]:
        await self.ensure_user(user_id)
        await self.ensure_cluster(cluster_id)
        return await GlobalBan.get_or_create(
            user_id=user_id, cluster_id=cluster_id, defaults=fields
        )

    async def delete_record(self, user_id: int, cluster_id: Optional[int]):
        await GlobalBan.filter(user_id=user_id, cluster_id=cluster_id).delete()

    async def all(self) -> List[GlobalBan]:
        return await GlobalBan.all().prefetch_related("user", "cluster")


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
                key = _make_cache_key(r.user_id, r.cluster_id)  # type: ignore
                self._cache[key] = _CachedGlobalBan(
                    id=r.id,
                    user_id=r.user_id,  # type: ignore
                    cluster_id=r.cluster_id,  # type: ignore
                    reason=r.reason,
                    created_by_id=r.created_by_id,  # type: ignore
                    created_at=r.created_at,
                    active=r.active,
                    lifted_by_id=r.lifted_by_id,  # type: ignore
                    lifted_at=r.lifted_at,
                )
        await super().initialize()

    async def add_ban(self, user_id: int, cluster_id: Optional[int], **fields):
        model, _ = await self.repo.ensure_record(user_id, cluster_id, **fields)
        key = _make_cache_key(user_id, cluster_id)
        async with self._lock:
            self._cache[key] = _CachedGlobalBan(
                id=model.id,
                user_id=model.user_id,  # type: ignore
                cluster_id=model.cluster_id,  # type: ignore
                reason=model.reason,
                created_by_id=model.created_by_id,  # type: ignore
                created_at=model.created_at,
                active=model.active,
                lifted_by_id=model.lifted_by_id,  # type: ignore
                lifted_at=model.lifted_at,
            )
            self._dirty.add(key)

    async def remove_ban(self, user_id: int, cluster_id: Optional[int]):
        key = _make_cache_key(user_id, cluster_id)
        async with self._lock:
            self._cache.pop(key, None)
            self._dirty.discard(key)
        await self.repo.delete_record(user_id, cluster_id)

    async def get_cluster_bans(
        self, cluster_id: Optional[int]
    ) -> List[_CachedGlobalBan]:
        async with self._lock:
            return [
                copy.deepcopy(v)
                for (_, cid), v in self._cache.items()
                if cid == cluster_id
            ]

    async def get_user_bans(self, user_id: int) -> List[_CachedGlobalBan]:
        async with self._lock:
            return [
                copy.deepcopy(v)
                for (uid, _), v in self._cache.items()
                if uid == user_id
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

        async with in_transaction():
            for k, v in payloads.items():
                await GlobalBan.update_or_create(
                    defaults=dict(
                        reason=v.reason,
                        created_by_id=v.created_by_id,
                        active=v.active,
                        lifted_by_id=v.lifted_by_id,
                        lifted_at=v.lifted_at,
                    ),
                    user_id=v.user_id,
                    cluster_id=v.cluster_id,
                )

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
