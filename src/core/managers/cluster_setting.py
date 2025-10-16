import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, TypeAlias
from tortoise.transactions import in_transaction
from src.core.managers.base import BaseCachedModel, BaseCacheManager, BaseManager, BaseRepository
from src.core.models import ClusterSetting


@dataclass
class _CachedClusterSetting(BaseCachedModel):
    id: Optional[int]
    cluster_id: int
    key: str
    value: Any


CacheKey: TypeAlias = Tuple[int, str]  # (cluster_id, key)
Cache: TypeAlias = Dict[CacheKey, _CachedClusterSetting]


def _make_cache_key(cluster_id: int, key: str) -> CacheKey:
    return (cluster_id, key)


class ClusterSettingRepository(BaseRepository):
    async def ensure_record(self, cluster_id: int, key: str, value: Any) -> ClusterSetting:
        obj, _ = await ClusterSetting.get_or_create(
            cluster_id=cluster_id,
            key=key,
            defaults={"value": value},
        )
        return obj

    async def delete_record(self, cluster_id: int, key: str):
        await ClusterSetting.filter(cluster_id=cluster_id, key=key).delete()

    async def all(self) -> List[ClusterSetting]:
        return await ClusterSetting.all()


class ClusterSettingCache(BaseCacheManager):
    def __init__(self, lock, repo: ClusterSettingRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache = cache
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for r in rows:
                key = _make_cache_key(r.cluster_id, r.key)  # type: ignore
                self._cache[key] = _CachedClusterSetting(
                    id=r.id,
                    cluster_id=r.cluster_id,  # type: ignore
                    key=r.key,
                    value=r.value,
                )
        await super().initialize()

    async def set(self, cluster_id: int, key: str, value: Any):
        record = await self.repo.ensure_record(cluster_id, key, value)
        cache_key = _make_cache_key(cluster_id, key)
        async with self._lock:
            self._cache[cache_key] = _CachedClusterSetting(
                id=record.id,
                cluster_id=cluster_id,
                key=key,
                value=value,
            )
            self._dirty.add(cache_key)

    async def get(self, cluster_id: int, key: str) -> Optional[Any]:
        cache_key = _make_cache_key(cluster_id, key)
        async with self._lock:
            r = self._cache.get(cache_key)
            return r.value if r else None

    async def remove(self, cluster_id: int, key: str):
        cache_key = _make_cache_key(cluster_id, key)
        async with self._lock:
            self._cache.pop(cache_key, None)
            self._dirty.discard(cache_key)
        await self.repo.delete_record(cluster_id, key)

    async def get_cluster_settings(self, cluster_id: int) -> List[_CachedClusterSetting]:
        async with self._lock:
            return [copy.deepcopy(v) for (c, _), v in self._cache.items() if c == cluster_id]

    async def sync(self, batch_size: int = 500):
        async with self._lock:
            dirty_snapshot = set(self._dirty)
            payloads = {k: copy.deepcopy(self._cache[k]) for k in dirty_snapshot if k in self._cache}
        if not payloads:
            return

        async with in_transaction():
            for _, cached in payloads.items():
                await ClusterSetting.update_or_create(
                    defaults={"value": cached.value},
                    cluster_id=cached.cluster_id,
                    key=cached.key,
                )

        async with self._lock:
            self._dirty -= dirty_snapshot


class ClusterSettingManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = ClusterSettingRepository(self._lock)
        self.cache = ClusterSettingCache(self._lock, self.repo, self._cache)

        self.set = self.cache.set
        self.get = self.cache.get
        self.remove = self.cache.remove
        self.get_cluster_settings = self.cache.get_cluster_settings
