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
from src.core.models import Chat, Mute, User


@dataclass
class _CachedMute(BaseCachedModel):
    id: Optional[int]
    tg_user_id: int
    tg_chat_id: int
    start_at: Any
    end_at: Optional[Any]
    reason: Optional[str]
    created_by_tg_id: Optional[int]
    active: bool
    auto_unmute: bool


CacheKey: TypeAlias = Tuple[int, int]  # (tg_user_id, tg_chat_id)
Cache: TypeAlias = Dict[CacheKey, _CachedMute]


def _make_cache_key(tg_user_id: int, tg_chat_id: int) -> CacheKey:
    return (tg_user_id, tg_chat_id)


class MuteRepository(BaseRepository):
    async def ensure_record(
        self, tg_user_id: int, tg_chat_id: int, **defaults
    ) -> Tuple[Mute, bool]:
        user, _ = await User.get_or_create(tg_user_id=tg_user_id)
        chat, _ = await Chat.get_or_create(tg_chat_id=tg_chat_id)
        created_by_id = None
        if "created_by_tg_id" in defaults:
            created_by_tg_id = defaults.pop("created_by_tg_id")
            if created_by_tg_id:
                created_by, _ = await User.get_or_create(tg_user_id=created_by_tg_id)
                created_by_id = created_by.id
        obj, created = await Mute.get_or_create(
            user_id=user.id, chat_id=chat.id, defaults={**defaults, "created_by_id": created_by_id}
        )
        return obj, created

    async def delete_record(self, tg_user_id: int, tg_chat_id: int):
        user = await User.filter(tg_user_id=tg_user_id).first()
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if user and chat:
            await Mute.filter(user_id=user.id, chat_id=chat.id).delete()

    async def all(self) -> List[Mute]:
        return await Mute.all().prefetch_related("user", "chat", "created_by")


class MuteCache(BaseCacheManager):
    def __init__(self, lock, repo: MuteRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache: Cache = cache
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for row in rows:
                key = _make_cache_key(row.user.tg_user_id, row.chat.tg_chat_id)  # type: ignore
                self._cache[key] = _CachedMute(
                    id=row.id,
                    tg_user_id=row.user.tg_user_id,  # type: ignore
                    tg_chat_id=row.chat.tg_chat_id,  # type: ignore
                    start_at=row.start_at,
                    end_at=row.end_at,
                    reason=row.reason,
                    created_by_tg_id=row.created_by.tg_user_id if row.created_by else None,  # type: ignore
                    active=row.active,
                    auto_unmute=row.auto_unmute,
                )
        await super().initialize()

    async def add_mute(self, tg_user_id: int, tg_chat_id: int, **fields):
        key = _make_cache_key(tg_user_id, tg_chat_id)
        async with self._lock:
            if key in self._cache:
                r = self._cache[key]
                for k, v in fields.items():
                    if hasattr(r, k):
                        setattr(r, k, v)
                self._dirty.add(key)
                return
        
        model, _ = await self.repo.ensure_record(tg_user_id, tg_chat_id, **fields)
        async with self._lock:
            self._cache[key] = _CachedMute(
                id=model.id,
                tg_user_id=tg_user_id,
                tg_chat_id=tg_chat_id,
                start_at=model.start_at,
                end_at=model.end_at,
                reason=model.reason,
                created_by_tg_id=fields.get("created_by_tg_id"),
                active=model.active,
                auto_unmute=model.auto_unmute,
            )

    async def remove_mute(self, tg_user_id: int, tg_chat_id: int):
        key = _make_cache_key(tg_user_id, tg_chat_id)
        async with self._lock:
            self._dirty.discard(key)
            self._cache.pop(key, None)
        await self.repo.delete_record(tg_user_id, tg_chat_id)

    async def get_user_mutes(self, tg_user_id: int) -> List[_CachedMute]:
        async with self._lock:
            return [
                copy.deepcopy(v) for k, v in self._cache.items() if k[0] == tg_user_id
            ]

    async def get_chat_mutes(self, tg_chat_id: int) -> List[_CachedMute]:
        async with self._lock:
            return [
                copy.deepcopy(v) for k, v in self._cache.items() if k[1] == tg_chat_id
            ]

    async def sync(self, batch_size: int = 500):
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
            tg_chat_ids = {k[1] for k in payloads.keys()}
            
            users = await User.filter(tg_user_id__in=list(tg_user_ids))
            chats = await Chat.filter(tg_chat_id__in=list(tg_chat_ids))
            user_map = {u.tg_user_id: u.id for u in users}
            chat_map = {c.tg_chat_id: c.id for c in chats}
            
            async with in_transaction():
                for k, v in payloads.items():
                    tg_user_id, tg_chat_id = k
                    if tg_user_id not in user_map or tg_chat_id not in chat_map:
                        continue
                    created_by_id = None
                    if v.created_by_tg_id:
                        cb_user = await User.filter(tg_user_id=v.created_by_tg_id).first()
                        if cb_user:
                            created_by_id = cb_user.id
                    await Mute.update_or_create(
                        defaults=dict(
                            start_at=v.start_at,
                            end_at=v.end_at,
                            reason=v.reason,
                            created_by_id=created_by_id,
                            active=v.active,
                            auto_unmute=v.auto_unmute,
                        ),
                        user_id=user_map[tg_user_id],
                        chat_id=chat_map[tg_chat_id],
                    )
        except Exception:
            from loguru import logger
            logger.exception("Mute sync failed")
            return

        async with self._lock:
            self._dirty -= dirty_snapshot


class MuteManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = MuteRepository(self._lock)
        self.cache = MuteCache(self._lock, self.repo, self._cache)

        self.add_mute = self.cache.add_mute
        self.remove_mute = self.cache.remove_mute
        self.get_user_mutes = self.cache.get_user_mutes
        self.get_chat_mutes = self.cache.get_chat_mutes

    async def get(self, tg_user_id: int, tg_chat_id: int) -> Optional[_CachedMute]:
        key = _make_cache_key(tg_user_id, tg_chat_id)
        async with self._lock:
            return copy.deepcopy(self._cache.get(key))
