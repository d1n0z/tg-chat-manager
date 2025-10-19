import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
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
from src.core.models import Chat, InviteLink, User


@dataclass
class _CachedInviteLink(BaseCachedModel):
    id: Optional[int]
    token: str
    tg_chat_id: int
    creator_tg_id: Optional[int]
    max_uses: int
    used_count: int
    expires_at: Optional[datetime]
    single_use: bool
    is_active: bool
    created_at: datetime


CacheKey: TypeAlias = str  # token
Cache: TypeAlias = Dict[CacheKey, _CachedInviteLink]


class InviteLinkRepository(BaseRepository):
    async def ensure_record(
        self,
        token: str,
        tg_chat_id: int,
        creator_tg_id: Optional[int] = None,
        max_uses: int = 1,
        expires_at: Optional[datetime] = None,
        single_use: bool = True,
    ) -> Tuple[InviteLink, bool]:
        chat, _ = await Chat.get_or_create(tg_chat_id=tg_chat_id)
        creator_id = None
        if creator_tg_id:
            creator, _ = await User.get_or_create(tg_user_id=creator_tg_id)
            creator_id = creator.id
        defaults = {
            "chat_id": chat.id,
            "creator_id": creator_id,
            "max_uses": max_uses,
            "expires_at": expires_at,
            "single_use": single_use,
        }
        obj, created = await InviteLink.get_or_create(token=token, defaults=defaults)
        return obj, created

    async def delete_record(self, token: str):
        await InviteLink.filter(token=token).delete()

    async def all(self) -> List[InviteLink]:
        return await InviteLink.all().prefetch_related("chat", "creator")


class InviteLinkCache(BaseCacheManager):
    def __init__(self, lock, repo: InviteLinkRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache: Cache = cache
        self._dirty: set[str] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for row in rows:
                self._cache[row.token] = _CachedInviteLink(
                    id=row.id,
                    token=row.token,
                    tg_chat_id=row.chat.tg_chat_id,  # type: ignore
                    creator_tg_id=row.creator.tg_user_id if row.creator else None,  # type: ignore
                    max_uses=row.max_uses,
                    used_count=row.used_count,
                    expires_at=row.expires_at,
                    single_use=row.single_use,
                    is_active=row.is_active,
                    created_at=row.created_at,
                )
        await super().initialize()

    @overload
    async def get(self, token: str, fields=None) -> Any: ...
    @overload
    async def get(self, token: str, fields: str) -> Any: ...
    @overload
    async def get(self, token: str, fields: Sequence[str]) -> Tuple[Any, ...]: ...

    async def get(self, token: str, fields: Union[None, str, Sequence[str]] = None):
        async with self._lock:
            obj = self._cache.get(token)
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

    async def add_invite(
        self,
        token: str,
        tg_chat_id: int,
        creator_tg_id: Optional[int] = None,
        max_uses: int = 1,
        expires_at: Optional[datetime] = None,
        single_use: bool = True,
    ):
        async with self._lock:
            if token in self._cache:
                return
        
        model, _ = await self.repo.ensure_record(
            token, tg_chat_id, creator_tg_id, max_uses, expires_at, single_use
        )
        async with self._lock:
            self._cache[token] = _CachedInviteLink(
                id=model.id,
                token=model.token,
                tg_chat_id=tg_chat_id,
                creator_tg_id=creator_tg_id,
                max_uses=model.max_uses,
                used_count=model.used_count,
                expires_at=model.expires_at,
                single_use=model.single_use,
                is_active=model.is_active,
                created_at=model.created_at,
            )
            self._dirty.add(token)

    async def remove_invite(self, token: str):
        async with self._lock:
            if token in self._cache:
                self._dirty.discard(token)
                del self._cache[token]
        await self.repo.delete_record(token)

    async def increment_usage(self, token: str) -> bool:
        async with self._lock:
            obj = self._cache.get(token)
            if not obj:
                return False
            obj.used_count += 1
            if obj.used_count >= obj.max_uses:
                obj.is_active = False
            self._dirty.add(token)
            return True

    async def get_chat_invites(self, tg_chat_id: int) -> List[_CachedInviteLink]:
        async with self._lock:
            return [
                copy.deepcopy(v) for v in self._cache.values() if v.tg_chat_id == tg_chat_id
            ]

    async def is_valid(self, token: str) -> bool:
        async with self._lock:
            invite = self._cache.get(token)
            if not invite:
                return False
            if not invite.is_active:
                return False
            if invite.expires_at and invite.expires_at < datetime.now(timezone.utc):
                return False
            if invite.used_count >= invite.max_uses:
                return False
            return True

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

        try:
            tg_chat_ids = {v.tg_chat_id for v in payloads.values()}
            chats = await Chat.filter(tg_chat_id__in=list(tg_chat_ids))
            chat_map = {c.tg_chat_id: c.id for c in chats}
            
            tokens = list(payloads.keys())
            existing_rows = await InviteLink.filter(token__in=tokens).prefetch_related(
                "chat", "creator"
            )
            existing_map = {row.token: row for row in existing_rows}

            to_update = []
            to_create = []

            for token, cached in payloads.items():
                if token in existing_map:
                    row = existing_map[token]
                    dirty = False
                    for field in ["used_count", "is_active"]:
                        if getattr(row, field) != getattr(cached, field):
                            setattr(row, field, getattr(cached, field))
                            dirty = True
                    if dirty:
                        to_update.append(row)
                else:
                    if cached.tg_chat_id not in chat_map:
                        continue
                    creator_id = None
                    if cached.creator_tg_id:
                        creator = await User.filter(tg_user_id=cached.creator_tg_id).first()
                        if creator:
                            creator_id = creator.id
                    to_create.append(
                        InviteLink(
                            token=cached.token,
                            chat_id=chat_map[cached.tg_chat_id],
                            creator_id=creator_id,
                            max_uses=cached.max_uses,
                            used_count=cached.used_count,
                            expires_at=cached.expires_at,
                            single_use=cached.single_use,
                            is_active=cached.is_active,
                        )
                    )

            async with in_transaction():
                if to_update:
                    await InviteLink.bulk_update(
                        to_update,
                        fields=["used_count", "is_active"],
                        batch_size=batch_size,
                    )
                if to_create:
                    await InviteLink.bulk_create(to_create, batch_size=batch_size)
        except Exception:
            from loguru import logger

            logger.exception("InviteLink sync failed")
            return

        async with self._lock:
            for token in payloads.keys():
                self._dirty.discard(token)


class InviteLinkManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = InviteLinkRepository(self._lock)
        self.cache = InviteLinkCache(self._lock, self.repo, self._cache)

        self.add_invite = self.cache.add_invite
        self.remove_invite = self.cache.remove_invite
        self.get = self.cache.get
        self.increment_usage = self.cache.increment_usage
        self.get_chat_invites = self.cache.get_chat_invites
        self.is_valid = self.cache.is_valid
