import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, TypeAlias
from tortoise.transactions import in_transaction
from src.core.managers.base import BaseCachedModel, BaseCacheManager, BaseManager, BaseRepository
from src.core.models import User, WelcomeMessage


@dataclass
class _CachedWelcome(BaseCachedModel):
    id: Optional[int]
    chat_id: Optional[int]
    text: str
    created_by_tg_id: Optional[int]
    created_at: Any
    is_default: bool


Cache: TypeAlias = Dict[Optional[int], _CachedWelcome]


class WelcomeRepository(BaseRepository):
    async def all(self) -> List[WelcomeMessage]:
        return await WelcomeMessage.all().prefetch_related("created_by")

    async def delete_record(self, chat_id: Optional[int]):
        await WelcomeMessage.filter(chat_id=chat_id).delete()

    async def ensure_record(self, chat_id: Optional[int], **fields) -> Tuple[WelcomeMessage, bool]:
        created_by_id = None
        if "created_by_tg_id" in fields:
            created_by_tg_id = fields.pop("created_by_tg_id")
            if created_by_tg_id:
                created_by, _ = await User.get_or_create(tg_user_id=created_by_tg_id)
                created_by_id = created_by.id
        return await WelcomeMessage.get_or_create(chat_id=chat_id, defaults={**fields, "created_by_id": created_by_id})


class WelcomeCache(BaseCacheManager):
    def __init__(self, lock, repo: WelcomeRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache = cache
        self._dirty: Set[Optional[int]] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for r in rows:
                self._cache[r.chat_id] = _CachedWelcome(  # type: ignore
                    id=r.id,
                    chat_id=r.chat_id,  # type: ignore
                    text=r.text,
                    created_by_tg_id=r.created_by.tg_user_id if r.created_by else None,  # type: ignore
                    created_at=r.created_at,
                    is_default=r.is_default,
                )
        await super().initialize()

    async def set_message(self, chat_id: Optional[int], text: str, created_by_tg_id: Optional[int], is_default=False):
        model, _ = await self.repo.ensure_record(chat_id, text=text, created_by_tg_id=created_by_tg_id, is_default=is_default)
        async with self._lock:
            self._cache[chat_id] = _CachedWelcome(
                id=model.id,
                chat_id=chat_id,
                text=text,
                created_by_tg_id=created_by_tg_id,
                created_at=model.created_at,
                is_default=is_default,
            )
            self._dirty.add(chat_id)

    async def remove_message(self, chat_id: Optional[int]):
        async with self._lock:
            self._cache.pop(chat_id, None)
            self._dirty.discard(chat_id)
        await self.repo.delete_record(chat_id)

    async def get(self, chat_id: Optional[int]) -> Optional[_CachedWelcome]:
        async with self._lock:
            return copy.deepcopy(self._cache.get(chat_id))

    async def sync(self, batch_size: int = 500):
        async with self._lock:
            dirty_snapshot = set(self._dirty)
            payloads = {cid: copy.deepcopy(self._cache[cid]) for cid in dirty_snapshot if cid in self._cache}
        if not payloads:
            return

        try:
            async with in_transaction():
                for cid, v in payloads.items():
                    created_by_id = None
                    if v.created_by_tg_id:
                        created_by = await User.filter(tg_user_id=v.created_by_tg_id).first()
                        if created_by:
                            created_by_id = created_by.id
                    await WelcomeMessage.update_or_create(
                        defaults=dict(
                            text=v.text,
                            created_by_id=created_by_id,
                            is_default=v.is_default,
                        ),
                        chat_id=cid,
                    )
        except Exception:
            from loguru import logger
            logger.exception("WelcomeMessage sync failed")
            return

        async with self._lock:
            self._dirty -= dirty_snapshot


class WelcomeMessageManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = WelcomeRepository(self._lock)
        self.cache = WelcomeCache(self._lock, self.repo, self._cache)

        self.set_message = self.cache.set_message
        self.remove_message = self.cache.remove_message
        self.get = self.cache.get
