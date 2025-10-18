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
from src.core.models import Chat, Nick, User


@dataclass
class _CachedNick(BaseCachedModel):
    id: Optional[int]
    tg_user_id: int
    tg_chat_id: int
    nick: str
    created_by_tg_id: Optional[int]
    created_at: Any


CacheKey: TypeAlias = Tuple[int, int]  # (tg_user_id, tg_chat_id)
Cache: TypeAlias = Dict[CacheKey, _CachedNick]


def _make_cache_key(tg_user_id: int, tg_chat_id: int) -> CacheKey:
    return (tg_user_id, tg_chat_id)


class NickRepository(BaseRepository):
    async def ensure_record(
        self,
        tg_user_id: int,
        tg_chat_id: int,
        nick: str,
        created_by_tg_id: Optional[int] = None,
    ) -> Tuple[Nick, bool]:
        user, _ = await User.get_or_create(tg_user_id=tg_user_id)
        chat, _ = await Chat.get_or_create(tg_chat_id=tg_chat_id)
        created_by_id = None
        if created_by_tg_id:
            created_by, _ = await User.get_or_create(tg_user_id=created_by_tg_id)
            created_by_id = created_by.id
        obj, created = await Nick.get_or_create(
            user_id=user.id,
            chat_id=chat.id,
            defaults={"nick": nick, "created_by_id": created_by_id},
        )
        if not created:
            obj.nick = nick
            obj.created_by_id = created_by_id
            await obj.save()
        return obj, created

    async def delete_record(self, tg_user_id: int, tg_chat_id: int):
        user = await User.filter(tg_user_id=tg_user_id).first()
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if user and chat:
            await Nick.filter(user_id=user.id, chat_id=chat.id).delete()

    async def all(self) -> List[Nick]:
        return await Nick.all().prefetch_related("user", "chat", "created_by")

    async def get_by_nick(self, tg_chat_id: int, nick: str) -> List[Tuple[str, int]]:
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if not chat:
            return []
        nicks = await Nick.filter(chat_id=chat.id, nick__icontains=nick).prefetch_related("user")
        return [(n.nick, n.user.tg_user_id) for n in nicks]


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
                key = _make_cache_key(row.user.tg_user_id, row.chat.tg_chat_id)  # type: ignore
                self._cache[key] = _CachedNick(
                    id=row.id,
                    tg_user_id=row.user.tg_user_id,  # type: ignore
                    tg_chat_id=row.chat.tg_chat_id,  # type: ignore
                    nick=row.nick,
                    created_by_tg_id=row.created_by.tg_user_id if row.created_by else None,  # type: ignore
                    created_at=row.created_at,
                )
        await super().initialize()

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
        tg_user_id: int,
        tg_chat_id: int,
        nick: str,
        created_by_tg_id: Optional[int] = None,
    ):
        key = _make_cache_key(tg_user_id, tg_chat_id)
        async with self._lock:
            if key in self._cache:
                r = self._cache[key]
                r.nick = nick
                r.created_by_tg_id = created_by_tg_id
                self._dirty.add(key)
                return
        
        model, created = await self.repo.ensure_record(tg_user_id, tg_chat_id, nick, created_by_tg_id)
        async with self._lock:
            self._cache[key] = _CachedNick(
                id=model.id,
                tg_user_id=tg_user_id,
                tg_chat_id=tg_chat_id,
                nick=model.nick,
                created_by_tg_id=created_by_tg_id,
                created_at=model.created_at,
            )

    async def remove_nick(self, tg_user_id: int, tg_chat_id: int):
        key = _make_cache_key(tg_user_id, tg_chat_id)
        async with self._lock:
            if key in self._cache:
                nick = self._cache[key]
                self._dirty.discard(key)
                del self._cache[key]
            else:
                nick = None
        await self.repo.delete_record(tg_user_id, tg_chat_id)
        return nick

    async def get_user_nicks(self, tg_user_id: int) -> List[_CachedNick]:
        async with self._lock:
            return [copy.deepcopy(v) for k, v in self._cache.items() if k[0] == tg_user_id]

    async def get_user_nick(self, tg_user_id: int, tg_chat_id: int) -> Optional[_CachedNick]:
        async with self._lock:
            nicks = [copy.deepcopy(v) for k, v in self._cache.items() if k[0] == tg_user_id and k[1] == tg_chat_id]
        if nicks:
            return nicks[0]
        return None

    async def get_chat_nicks(self, tg_chat_id: int) -> List[_CachedNick]:
        async with self._lock:
            return [
                copy.deepcopy(v) for k, v in self._cache.items() if k[1] == tg_chat_id
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
            tg_user_ids = {key[0] for key in payloads.keys()}
            tg_chat_ids = {key[1] for key in payloads.keys()}
            
            users = await User.filter(tg_user_id__in=list(tg_user_ids))
            chats = await Chat.filter(tg_chat_id__in=list(tg_chat_ids))
            user_map = {u.tg_user_id: u.id for u in users}
            chat_map = {c.tg_chat_id: c.id for c in chats}
            
            user_db_ids = [user_map[k[0]] for k in payloads.keys() if k[0] in user_map and k[1] in chat_map]
            existing_rows = await Nick.filter(
                user_id__in=user_db_ids
            ).prefetch_related("user", "chat", "created_by")
            existing_map = {(row.user.tg_user_id, row.chat.tg_chat_id): row for row in existing_rows}  # type: ignore

            to_update = []
            to_create = []

            for key, cached in items:
                tg_user_id, tg_chat_id = key
                if key in existing_map:
                    row = existing_map[key]
                    dirty = False
                    if row.nick != cached.nick:
                        row.nick = cached.nick
                        dirty = True
                    created_by_id = None
                    if cached.created_by_tg_id:
                        cb_user = await User.filter(tg_user_id=cached.created_by_tg_id).first()
                        if cb_user:
                            created_by_id = cb_user.id
                    if getattr(row, "created_by_id", None) != created_by_id:
                        row.created_by_id = created_by_id
                        dirty = True
                    if dirty:
                        to_update.append(row)
                else:
                    if tg_user_id not in user_map or tg_chat_id not in chat_map:
                        continue
                    created_by_id = None
                    if cached.created_by_tg_id:
                        cb_user = await User.filter(tg_user_id=cached.created_by_tg_id).first()
                        if cb_user:
                            created_by_id = cb_user.id
                    to_create.append(
                        Nick(
                            user_id=user_map[tg_user_id],
                            chat_id=chat_map[tg_chat_id],
                            nick=cached.nick,
                            created_by_id=created_by_id,
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

        self.get = self.cache.get
        self.add_nick = self.cache.add_nick
        self.remove_nick = self.cache.remove_nick
        self.get_user_nicks = self.cache.get_user_nicks
        self.get_user_nick = self.cache.get_user_nick
        self.get_chat_nicks = self.cache.get_chat_nicks
    
    def make_cache_key(self, tg_user_id: int, tg_chat_id: int) -> CacheKey:
        return _make_cache_key(tg_user_id, tg_chat_id)

    async def user_has_nick(self, tg_user_id: int, tg_chat_id: int) -> bool:
        nick = await self.get(_make_cache_key(tg_user_id, tg_chat_id), "nick")
        return nick is not None
    
    async def get_by_nick(self, tg_chat_id: int, nick: str) -> List[Tuple[str, int]]:
        return await self.repo.get_by_nick(tg_chat_id, nick)
