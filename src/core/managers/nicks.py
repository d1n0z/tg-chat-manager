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

from tortoise.transactions import in_transaction

from src.core.managers.base import (
    BaseCachedModel,
    BaseCacheManager,
    BaseManager,
    BaseRepository,
)
from src.core.models import Cluster, Nick, User


@dataclass
class _CachedNick(BaseCachedModel):
    id: Optional[int]
    user_id: int
    cluster_id: Optional[int]
    nick: str
    created_by_id: Optional[int]
    created_at: Any


CacheKey: TypeAlias = Tuple[int, Optional[int]]  # (user_id, cluster_id)
Cache: TypeAlias = Dict[CacheKey, _CachedNick]


def _make_cache_key(user_id: int, cluster_id: Optional[int]) -> CacheKey:
    return (user_id, cluster_id)


class NickRepository(BaseRepository):
    async def ensure_user(self, user_id: int) -> User:
        return await User.get(id=user_id)

    async def ensure_cluster(self, cluster_id: Optional[int]) -> Optional[Cluster]:
        if cluster_id is None:
            return None
        return await Cluster.get(id=cluster_id)

    async def ensure_record(
        self,
        user_id: int,
        cluster_id: Optional[int],
        nick: str,
        created_by_id: Optional[int] = None,
    ) -> Tuple[Nick, bool]:
        defaults = {"nick": nick, "created_by_id": created_by_id}
        obj, created = await Nick.get_or_create(
            user_id=user_id,
            cluster_id=cluster_id,
            defaults=defaults,
        )
        return obj, created

    async def delete_record(self, user_id: int, cluster_id: Optional[int]):
        await Nick.filter(user_id=user_id, cluster_id=cluster_id).delete()

    async def all(self) -> List[Nick]:
        return await Nick.all().prefetch_related("user", "cluster", "created_by")


class NickCache(BaseCacheManager):
    def __init__(self, lock, repo: NickRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache: Cache = cache
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for row in rows:
                key = _make_cache_key(row.user_id, row.cluster_id)  # type: ignore
                self._cache[key] = _CachedNick(
                    id=row.id,
                    user_id=row.user_id,  # type: ignore
                    cluster_id=row.cluster_id,  # type: ignore
                    nick=row.nick,
                    created_by_id=row.created_by_id,  # type: ignore
                    created_at=row.created_at,
                )
        await super().initialize()

    async def _ensure_cached(
        self,
        user_id: int,
        cluster_id: Optional[int],
        nick: str,
        created_by_id: Optional[int] = None,
    ) -> bool:
        key = _make_cache_key(user_id, cluster_id)
        async with self._lock:
            if key in self._cache:
                return False

        model, created = await self.repo.ensure_record(
            user_id, cluster_id, nick, created_by_id
        )
        async with self._lock:
            self._cache[key] = _CachedNick(
                id=model.id,
                user_id=model.user_id,  # type: ignore
                cluster_id=model.cluster_id,  # type: ignore
                nick=model.nick,
                created_by_id=model.created_by_id,  # type: ignore
                created_at=model.created_at,
            )
        return created

    @overload
    async def get(self, cache_key: CacheKey, fields=None) -> Any: ...
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
            return getattr(obj, fields, None) if obj else None
        else:
            return (
                tuple([getattr(obj, f, None) for f in fields])
                if obj
                else tuple([None for _ in fields])
            )

    async def add_nick(
        self,
        user_id: int,
        cluster_id: Optional[int],
        nick: str,
        created_by_id: Optional[int] = None,
    ):
        await self._ensure_cached(user_id, cluster_id, nick, created_by_id)
        key = _make_cache_key(user_id, cluster_id)
        async with self._lock:
            r = self._cache[key]
            r.nick = nick
            r.created_by_id = created_by_id
            self._dirty.add(key)

    async def remove_nick(self, user_id: int, cluster_id: Optional[int]):
        key = _make_cache_key(user_id, cluster_id)
        async with self._lock:
            if key in self._cache:
                self._dirty.discard(key)
                del self._cache[key]
        await self.repo.delete_record(user_id, cluster_id)

    async def get_user_nicks(self, user_id: int) -> List[_CachedNick]:
        async with self._lock:
            return [copy.deepcopy(v) for k, v in self._cache.items() if k[0] == user_id]

    async def get_cluster_nicks(self, cluster_id: Optional[int]) -> List[_CachedNick]:
        async with self._lock:
            return [
                copy.deepcopy(v) for k, v in self._cache.items() if k[1] == cluster_id
            ]

    async def sync(self, batch_size: int = 1000):
        async with self._lock:
            if not self._dirty:
                return
            dirty_snapshot = set(self._dirty)
            payloads = {
                k: copy.deepcopy(self._cache[k])
                for k in dirty_snapshot
                if k in self._cache
            }

        if not payloads:
            return

        items = list(payloads.items())
        try:
            user_ids = {key[0] for key in payloads.keys()}
            existing_rows = await Nick.filter(
                user_id__in=list(user_ids)
            ).prefetch_related("user", "cluster")
            existing_map = {(row.user_id, row.cluster_id): row for row in existing_rows}  # type: ignore

            to_update = []
            to_create = []

            for key, cached in items:
                if key in existing_map:
                    row = existing_map[key]
                    dirty = False
                    if row.nick != cached.nick:
                        row.nick = cached.nick
                        dirty = True
                    if getattr(row, "created_by_id", None) != cached.created_by_id:
                        row.created_by_id = cached.created_by_id
                        dirty = True
                    if dirty:
                        to_update.append(row)
                else:
                    if cached.user_id is None:
                        continue
                    to_create.append(
                        Nick(
                            user_id=cached.user_id,
                            cluster_id=cached.cluster_id,
                            nick=cached.nick,
                            created_by_id=cached.created_by_id,
                        )
                    )

            async with in_transaction():
                if to_update:
                    await Nick.bulk_update(
                        to_update,
                        fields=["nick", "created_by_id"],
                        batch_size=batch_size,
                    )
                if to_create:
                    await Nick.bulk_create(to_create, batch_size=batch_size)
        except Exception:
            from loguru import logger

            logger.exception("Nick sync failed")
            return

        async with self._lock:
            for key in payloads.keys():
                self._dirty.discard(key)


class NickManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = NickRepository(self._lock)
        self.cache = NickCache(self._lock, self.repo, self._cache)

        self.add_nick = self.cache.add_nick
        self.remove_nick = self.cache.remove_nick
        self.get = self.cache.get
        self.get_user_nicks = self.cache.get_user_nicks
        self.get_cluster_nicks = self.cache.get_cluster_nicks

    async def user_has_nick(self, user_id: int, cluster_id: Optional[int]) -> bool:
        nick = await self.get(_make_cache_key(user_id, cluster_id), "nick")
        return nick is not None
