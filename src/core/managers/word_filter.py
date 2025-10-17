import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, TypeAlias

from src.core.managers.base import (
    BaseCachedModel,
    BaseCacheManager,
    BaseManager,
    BaseRepository,
)
from src.core.models import Chat, User, WordFilter


@dataclass
class _CachedWordFilter(BaseCachedModel):
    id: Optional[int]
    tg_chat_id: int
    chat_id: Optional[int]
    word: str
    added_by_tg: Optional[int]
    added_by_id: Optional[int]
    added_at: Any


CacheKey: TypeAlias = Tuple[int, str]  # (tg_chat_id, word)
Cache: TypeAlias = Dict[CacheKey, _CachedWordFilter]


def _make_cache_key(tg_chat_id: int, word: str) -> CacheKey:
    return (tg_chat_id, word.lower())


class WordFilterRepository(BaseRepository):
    async def ensure_chat(self, tg_chat_id: int) -> Tuple[Chat, bool]:
        return await Chat.get_or_create(tg_chat_id=tg_chat_id, defaults={})

    async def ensure_user(self, tg_user_id: int) -> Tuple[User, bool]:
        return await User.get_or_create(tg_user_id=tg_user_id, defaults={})

    async def get_all(self) -> List[WordFilter]:
        return await WordFilter.all().prefetch_related("chat", "added_by")

    async def delete_record(self, tg_chat_id: int, word: str):
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if not chat:
            return
        await WordFilter.filter(chat_id=chat.id, word=word.lower()).delete()


class WordFilterCache(BaseCacheManager):
    def __init__(self, lock, repo: WordFilterRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache: Cache = cache
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.get_all()
        async with self._lock:
            for row in rows:
                key = _make_cache_key(row.chat.tg_chat_id, row.word)
                self._cache[key] = _CachedWordFilter(
                    id=row.id,
                    tg_chat_id=row.chat.tg_chat_id,
                    chat_id=row.chat_id,  # type: ignore
                    word=row.word.lower(),
                    added_by_tg=row.added_by.tg_user_id if row.added_by else None,
                    added_by_id=row.added_by_id if hasattr(row, "added_by_id") else None,  # type: ignore
                    added_at=row.added_at,
                )
        await super().initialize()

    async def add_word(self, tg_chat_id: int, word: str, added_by_tg: Optional[int] = None):
        word = word.lower()
        key = _make_cache_key(tg_chat_id, word)
        
        async with self._lock:
            if key in self._cache:
                return

        chat, _ = await self.repo.ensure_chat(tg_chat_id)
        added_by_id = None
        if added_by_tg:
            user, _ = await self.repo.ensure_user(added_by_tg)
            added_by_id = user.id

        obj = await WordFilter.create(
            chat_id=chat.id,
            word=word,
            added_by_id=added_by_id,
        )

        async with self._lock:
            self._cache[key] = _CachedWordFilter(
                id=obj.id,
                tg_chat_id=tg_chat_id,
                chat_id=chat.id,
                word=word,
                added_by_tg=added_by_tg,
                added_by_id=added_by_id,
                added_at=obj.added_at,
            )

    async def remove_word(self, tg_chat_id: int, word: str):
        word = word.lower()
        key = _make_cache_key(tg_chat_id, word)
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
        await self.repo.delete_record(tg_chat_id, word)

    async def get_chat_words(self, tg_chat_id: int) -> List[str]:
        async with self._lock:
            return [
                v.word for k, v in self._cache.items() if k[0] == tg_chat_id
            ]

    async def sync(self, batch_size: int = 1000):
        pass


class WordFilterManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = WordFilterRepository(self._lock)
        self.cache = WordFilterCache(self._lock, self.repo, self._cache)

        self.add_word = self.cache.add_word
        self.remove_word = self.cache.remove_word
        self.get_chat_words = self.cache.get_chat_words
