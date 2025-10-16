import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, TypeAlias
from src.core.managers.base import BaseCachedModel, BaseCacheManager, BaseManager, BaseRepository
from src.core.models import NewsBroadcast


@dataclass
class _CachedNewsBroadcast(BaseCachedModel):
    id: Optional[int]
    cluster_id: Optional[int]
    actor_id: Optional[int]
    content: str
    sent_count: int
    success_count: int
    failed_count: int
    meta: Optional[dict]
    created_at: Any


Cache: TypeAlias = Dict[int, _CachedNewsBroadcast]


class NewsBroadcastRepository(BaseRepository):
    async def all(self) -> List[NewsBroadcast]:
        return await NewsBroadcast.all().prefetch_related("cluster", "actor")

    async def ensure_record(self, cluster_id: Optional[int], **fields) -> NewsBroadcast:
        return await NewsBroadcast.create(cluster_id=cluster_id, **fields)


class NewsBroadcastCache(BaseCacheManager):
    def __init__(self, lock, repo: NewsBroadcastRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache = cache
        self._dirty: Set[int] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for r in rows:
                self._cache[r.id] = _CachedNewsBroadcast(
                    id=r.id,
                    cluster_id=r.cluster_id,  # type: ignore
                    actor_id=r.actor_id,  # type: ignore
                    content=r.content,
                    sent_count=r.sent_count,
                    success_count=r.success_count,
                    failed_count=r.failed_count,
                    meta=r.meta,
                    created_at=r.created_at,
                )
        await super().initialize()

    async def add_broadcast(self, cluster_id: Optional[int], content: str, actor_id: Optional[int], meta: Optional[dict] = None):
        model = await self.repo.ensure_record(cluster_id, content=content, actor_id=actor_id, meta=meta)
        async with self._lock:
            self._cache[model.id] = _CachedNewsBroadcast(
                id=model.id,
                cluster_id=model.cluster_id,  # type: ignore
                actor_id=model.actor_id,  # type: ignore
                content=model.content,
                sent_count=model.sent_count,
                success_count=model.success_count,
                failed_count=model.failed_count,
                meta=model.meta,
                created_at=model.created_at,
            )
            self._dirty.add(model.id)

    async def get_cluster_broadcasts(self, cluster_id: Optional[int]) -> List[_CachedNewsBroadcast]:
        async with self._lock:
            return [copy.deepcopy(v) for v in self._cache.values() if v.cluster_id == cluster_id]

    async def sync(self, batch_size: int = 500):
        # Обычно NewsBroadcast создаются раз и больше не редактируются, так что sync здесь может быть минимальным
        async with self._lock:
            self._dirty.clear()


class NewsBroadcastManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = NewsBroadcastRepository(self._lock)
        self.cache = NewsBroadcastCache(self._lock, self.repo, self._cache)

        self.add_broadcast = self.cache.add_broadcast
        self.get_cluster_broadcasts = self.cache.get_cluster_broadcasts
