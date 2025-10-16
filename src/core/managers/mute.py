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
    user_id: int
    chat_id: int
    start_at: Any
    end_at: Optional[Any]
    reason: Optional[str]
    created_by_id: Optional[int]
    active: bool
    auto_unmute: bool


CacheKey: TypeAlias = Tuple[int, int]  # (user_id, chat_id)
Cache: TypeAlias = Dict[CacheKey, _CachedMute]


def _make_cache_key(user_id: int, chat_id: int) -> CacheKey:
    return (user_id, chat_id)


class MuteRepository(BaseRepository):
    async def ensure_user(self, tg_user_id: int) -> Tuple[User, bool]:
        return await User.get_or_create(tg_user_id=tg_user_id, defaults={})

    async def ensure_chat(self, tg_chat_id: int) -> Tuple[Chat, bool]:
        return await Chat.get_or_create(tg_chat_id=tg_chat_id, defaults={})

    async def ensure_record(
        self, user_id: int, chat_id: int, **defaults
    ) -> Tuple[Mute, bool]:
        user, _ = await self.ensure_user(user_id)
        chat, _ = await self.ensure_chat(chat_id)
        obj, created = await Mute.get_or_create(
            user_id=user.id, chat_id=chat.id, defaults=defaults
        )
        return obj, created

    async def delete_record(self, user_tg_id: int, chat_tg_id: int):
        rows = await Mute.filter(user__tg_user_id=user_tg_id, chat__tg_chat_id=chat_tg_id)
        await Mute.filter(id__in=[r.id for r in rows]).delete()

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
                key = _make_cache_key(row.user_id, row.chat_id)  # type: ignore
                self._cache[key] = _CachedMute(
                    id=row.id,
                    user_id=row.user_id,  # type: ignore
                    chat_id=row.chat_id,  # type: ignore
                    start_at=row.start_at,
                    end_at=row.end_at,
                    reason=row.reason,
                    created_by_id=row.created_by_id,  # type: ignore
                    active=row.active,
                    auto_unmute=row.auto_unmute,
                )
        await super().initialize()

    async def ensure_cached(self, user_id: int, chat_id: int, **fields):
        key = _make_cache_key(user_id, chat_id)
        async with self._lock:
            if key in self._cache:
                return self._cache[key], False

        model, created = await self.repo.ensure_record(
            user_id=user_id,  # type: ignore
            chat_id=chat_id,  # type: ignore
            **fields,
        )

        async with self._lock:
            self._cache[key] = _CachedMute(
                id=model.id,
                user_id=model.user_id,  # type: ignore
                chat_id=model.chat_id,  # type: ignore
                reason=model.reason,
                active=model.active,
                auto_unmute=model.auto_unmute,
                created_by_id=model.created_by_id,  # type: ignore
                start_at=model.start_at,
                end_at=model.end_at,
            )
        return model, created

    async def add_mute(self, user_id: int, chat_id: int, **fields):
        key = _make_cache_key(user_id, chat_id)
        model, _ = await self.ensure_cached(user_id, chat_id, **fields)
        async with self._lock:
            self._cache[key] = _CachedMute(
                id=model.id,
                user_id=model.user_id,  # type: ignore
                chat_id=model.chat_id,  # type: ignore
                start_at=model.start_at,
                end_at=model.end_at,
                reason=model.reason,
                created_by_id=model.created_by_id,  # type: ignore
                active=model.active,
                auto_unmute=model.auto_unmute,
            )
            self._dirty.add(key)

    async def remove_mute(self, user_id: int, chat_id: int):
        key = _make_cache_key(user_id, chat_id)
        async with self._lock:
            self._dirty.discard(key)
            self._cache.pop(key, None)
        await self.repo.delete_record(user_id, chat_id)

    async def get_user_mutes(self, user_id: int) -> List[_CachedMute]:
        async with self._lock:
            return [
                copy.deepcopy(v) for (u, _), v in self._cache.items() if u == user_id
            ]

    async def get_chat_mutes(self, chat_id: int) -> List[_CachedMute]:
        async with self._lock:
            return [
                copy.deepcopy(v) for (_, c), v in self._cache.items() if c == chat_id
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

        async with in_transaction():
            for _, v in payloads.items():
                await Mute.update_or_create(
                    defaults=dict(
                        start_at=v.start_at,
                        end_at=v.end_at,
                        reason=v.reason,
                        created_by_id=v.created_by_id,
                        active=v.active,
                        auto_unmute=v.auto_unmute,
                    ),
                    user_id=v.user_id,
                    chat_id=v.chat_id,
                )

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
