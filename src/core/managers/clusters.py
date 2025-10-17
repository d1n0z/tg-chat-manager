import asyncio
import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, TypeAlias

from loguru import logger
from tortoise.transactions import in_transaction

from src.core.managers.base import (
    BaseCachedModel,
    BaseCacheManager,
    BaseManager,
    BaseRepository,
)
from src.core.models import Chat, Cluster

DEFAULT_CLUSTER = {
    "name": "GLOBAL",
    "slug": "global",
    "is_global": True,
}


@dataclass
class _CachedCluster(BaseCachedModel):
    id: int
    name: str
    is_global: bool
    created_at: Any
    chat_ids: Set[int]
    slug: Optional[str] = None


CacheKey: TypeAlias = int  # cluster_id
Cache: TypeAlias = Dict[CacheKey, _CachedCluster]


class ClusterRepository(BaseRepository):
    async def ensure_record(
        self,
        name: str,
        defaults: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Cluster, bool]:
        defaults = defaults or {}
        merged_defaults = {
            **{k: v for k, v in DEFAULT_CLUSTER.items() if k not in {"name"}},
            **defaults,
        }
        obj, created = await Cluster.get_or_create(
            name=name,
            defaults=merged_defaults,
        )
        return obj, created

    async def get_record(self, cluster_id: int) -> Optional[Cluster]:
        return await Cluster.filter(id=cluster_id).first()

    async def get_global(self) -> Cluster:
        return await Cluster.get(is_global=True)

    async def delete_record(self, cluster_id: int):
        await Cluster.filter(id=cluster_id).delete()

    async def get_all_with_chats(self) -> List[Cluster]:
        return await Cluster.all().prefetch_related("chats")


class ClusterCache(BaseCacheManager):
    def __init__(self, lock: asyncio.Lock, repo: ClusterRepository, cache: Cache):
        super().__init__(lock)
        self._cache: Cache = cache
        self.repo = repo
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.get_all_with_chats()
        async with self._lock:
            for cluster in rows:
                self._cache[cluster.id] = _CachedCluster(
                    id=cluster.id,
                    name=cluster.name,
                    slug=cluster.slug,
                    is_global=cluster.is_global,
                    created_at=cluster.created_at,
                    chat_ids={chat.tg_chat_id for chat in cluster.chats},
                )
        await super().initialize()

    async def get(self, cluster_id: int) -> Optional[_CachedCluster]:
        async with self._lock:
            return self._cache.get(cluster_id)

    async def add_chat(self, cluster_id: int, tg_chat_id: int):
        async with self._lock:
            if cluster_id not in self._cache:
                cluster = await self.repo.get_record(cluster_id)
                if not cluster:
                    return
                self._cache[cluster_id] = _CachedCluster(
                    id=cluster.id,
                    name=cluster.name,
                    slug=cluster.slug,
                    is_global=cluster.is_global,
                    created_at=cluster.created_at,
                    chat_ids=set(),
                )
            self._cache[cluster_id].chat_ids.add(tg_chat_id)
            self._dirty.add(cluster_id)

    async def remove_chat(self, cluster_id: int, tg_chat_id: int):
        async with self._lock:
            cluster = self._cache.get(cluster_id)
            if cluster and tg_chat_id in cluster.chat_ids:
                cluster.chat_ids.remove(tg_chat_id)
                self._dirty.add(cluster_id)

    async def add_cluster(self, name: str, **defaults) -> Cluster:
        obj, _ = await self.repo.ensure_record(name, defaults)
        async with self._lock:
            self._cache[obj.id] = _CachedCluster(
                id=obj.id,
                name=obj.name,
                slug=obj.slug,
                is_global=obj.is_global,
                created_at=obj.created_at,
                chat_ids=set(),
            )
        return obj

    async def remove_cluster(self, cluster_id: int):
        await self.repo.delete_record(cluster_id)
        async with self._lock:
            self._cache.pop(cluster_id, None)
            self._dirty.discard(cluster_id)

    async def sync(self, batch_size: int = 1000):
        async with self._lock:
            if not self._dirty:
                return
            dirty_snapshot = copy.deepcopy(self._dirty)
            cache_snapshot = {
                cid: copy.deepcopy(self._cache[cid])
                for cid in dirty_snapshot
                if cid in self._cache
            }

        succeeded_clusters: Set[int] = set()
        async with in_transaction() as conn:
            for cluster_id, cached in cache_snapshot.items():
                db_chats = await Chat.filter(cluster_id=cluster_id).using_db(conn)
                db_tg_chat_ids = {chat.tg_chat_id for chat in db_chats}

                to_add = cached.chat_ids - db_tg_chat_ids
                to_remove = db_tg_chat_ids - cached.chat_ids

                add_updated = 0

                if to_add:
                    add_updated = (
                        await Chat.filter(tg_chat_id__in=to_add)
                        .using_db(conn)
                        .update(cluster_id=cluster_id)
                    )
                if to_remove:
                    await (
                        Chat.filter(tg_chat_id__in=to_remove)
                        .using_db(conn)
                        .update(cluster_id=None)
                    )

                if not to_add or add_updated >= len(to_add):
                    succeeded_clusters.add(cluster_id)
                else:
                    logger.warning(
                        f"ClusterCache.sync: cluster {cluster_id} - only {add_updated} of {len(to_add)} chats added"
                    )

        async with self._lock:
            self._dirty -= succeeded_clusters


class ClusterManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = ClusterRepository(self._lock)
        self.cache = ClusterCache(self._lock, self.repo, self._cache)

        self.add_chat = self.cache.add_chat
        self.remove_chat = self.cache.remove_chat
        self.get_cluster = self.cache.get
        self.add_cluster = self.cache.add_cluster
        self.remove_cluster = self.cache.remove_cluster

    async def get_chats(self, cluster_id: int) -> List[int]:
        cluster = await self.cache.get(cluster_id)
        return list(cluster.chat_ids) if cluster else []

    async def get_all_clusters(self) -> List[_CachedCluster]:
        async with self._lock:
            return [copy.deepcopy(c) for c in self.cache._cache.values()]
