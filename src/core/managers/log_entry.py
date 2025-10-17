import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, TypeAlias
from src.core.managers.base import BaseCachedModel, BaseCacheManager, BaseManager, BaseRepository
from src.core.models import Chat, LogEntry, User


@dataclass
class _CachedLogEntry(BaseCachedModel):
    id: Optional[int]
    cluster_id: Optional[int]
    tg_chat_id: Optional[int]
    action: str
    target_tg_user_id: Optional[int]
    actor_tg_user_id: Optional[int]
    reason: Optional[str]
    meta: Optional[dict]
    created_at: Any


Cache: TypeAlias = Dict[int, _CachedLogEntry]


class LogEntryRepository(BaseRepository):
    async def all(self) -> List[LogEntry]:
        return await LogEntry.all().prefetch_related("cluster", "chat", "target_user", "actor_user")

    async def ensure_record(self, **fields) -> LogEntry:
        chat_id = None
        if "tg_chat_id" in fields:
            tg_chat_id = fields.pop("tg_chat_id")
            if tg_chat_id:
                chat, _ = await Chat.get_or_create(tg_chat_id=tg_chat_id)
                chat_id = chat.id
        target_user_id = None
        if "target_tg_user_id" in fields:
            target_tg_user_id = fields.pop("target_tg_user_id")
            if target_tg_user_id:
                target_user, _ = await User.get_or_create(tg_user_id=target_tg_user_id)
                target_user_id = target_user.id
        actor_user_id = None
        if "actor_tg_user_id" in fields:
            actor_tg_user_id = fields.pop("actor_tg_user_id")
            if actor_tg_user_id:
                actor_user, _ = await User.get_or_create(tg_user_id=actor_tg_user_id)
                actor_user_id = actor_user.id
        return await LogEntry.create(chat_id=chat_id, target_user_id=target_user_id, actor_user_id=actor_user_id, **fields)


class LogEntryCache(BaseCacheManager):
    def __init__(self, lock, repo: LogEntryRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache = cache
        self._dirty: Set[int] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for r in rows:
                self._cache[r.id] = _CachedLogEntry(
                    id=r.id,
                    cluster_id=r.cluster_id,  # type: ignore
                    tg_chat_id=r.chat.tg_chat_id if r.chat else None,  # type: ignore
                    action=r.action,
                    target_tg_user_id=r.target_user.tg_user_id if r.target_user else None,  # type: ignore
                    actor_tg_user_id=r.actor_user.tg_user_id if r.actor_user else None,  # type: ignore
                    reason=r.reason,
                    meta=r.meta,
                    created_at=r.created_at,
                )
        await super().initialize()

    async def add_log(self, **fields):
        model = await self.repo.ensure_record(**fields)
        async with self._lock:
            self._cache[model.id] = _CachedLogEntry(
                id=model.id,
                cluster_id=model.cluster_id,  # type: ignore
                tg_chat_id=fields.get("tg_chat_id"),
                action=model.action,
                target_tg_user_id=fields.get("target_tg_user_id"),
                actor_tg_user_id=fields.get("actor_tg_user_id"),
                reason=model.reason,
                meta=model.meta,
                created_at=model.created_at,
            )
            self._dirty.add(model.id)

    async def get_cluster_logs(self, cluster_id: Optional[int]) -> List[_CachedLogEntry]:
        async with self._lock:
            return [copy.deepcopy(v) for v in self._cache.values() if v.cluster_id == cluster_id]

    async def sync(self, batch_size: int = 500):
        async with self._lock:
            self._dirty.clear()


class LogEntryManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = LogEntryRepository(self._lock)
        self.cache = LogEntryCache(self._lock, self.repo, self._cache)

        self.add_log = self.cache.add_log
        self.get_cluster_logs = self.cache.get_cluster_logs
