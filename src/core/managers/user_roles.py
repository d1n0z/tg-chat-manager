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

from src.core import enums
from src.core.config import settings
from src.core.managers.base import (
    BaseCachedModel,
    BaseCacheManager,
    BaseManager,
    BaseRepository,
)
from src.core.models import Chat, User, UserRole


@dataclass
class _CachedUserRole(BaseCachedModel):
    id: Optional[int]
    tg_user_id: int
    user_id: Optional[int]
    tg_chat_id: int
    chat_id: Optional[int]
    level: enums.Role
    assigned_by_tg: Optional[int]
    assigned_by_id: Optional[int]
    assigned_at: Any


CacheKey: TypeAlias = Tuple[int, int]  # (tg_user_id, tg_chat_id)
Cache: TypeAlias = Dict[CacheKey, _CachedUserRole]


def _make_cache_key(tg_user_id: int, tg_chat_id: int) -> CacheKey:
    return (tg_user_id, tg_chat_id)


class UserRoleRepository(BaseRepository):
    async def ensure_user(self, tg_user_id: int) -> Tuple[User, bool]:
        return await User.get_or_create(tg_user_id=tg_user_id, defaults={})

    async def ensure_chat(self, tg_chat_id: int) -> Tuple[Chat, bool]:
        return await Chat.get_or_create(tg_chat_id=tg_chat_id, defaults={})

    async def ensure_record(
        self,
        tg_user_id: int,
        tg_chat_id: int,
        defaults: Optional[Dict[str, Any]] = None,
    ) -> Tuple[UserRole, bool]:
        defaults = defaults or {}
        user, _ = await self.ensure_user(tg_user_id)
        chat, _ = await self.ensure_chat(tg_chat_id)
        obj, created = await UserRole.get_or_create(
            user_id=user.id,
            chat_id=chat.id,
            defaults={**defaults},
        )
        return obj, created

    async def get_record(self, tg_user_id: int, tg_chat_id: int) -> Optional[UserRole]:
        return await UserRole.filter(
            user__tg_user_id=tg_user_id, chat__tg_chat_id=tg_chat_id
        ).first()

    async def delete_record(self, tg_user_id: int, tg_chat_id: int):
        user = await User.filter(tg_user_id=tg_user_id).first()
        chat = await Chat.filter(tg_chat_id=tg_chat_id).first()
        if not user or not chat:
            return
        await UserRole.filter(user_id=user.id, chat_id=chat.id).delete()

    async def all(self) -> List[UserRole]:
        return await UserRole.all().prefetch_related("user", "assigned_by", "chat")


class UserRoleCache(BaseCacheManager):
    def __init__(self, lock, repo: UserRoleRepository, cache: Cache):
        super().__init__(lock)
        self.repo = repo
        self._cache: Cache = cache
        self._dirty: Set[CacheKey] = set()

    async def initialize(self):
        rows = await self.repo.all()
        async with self._lock:
            for row in rows:
                key = _make_cache_key(row.user.tg_user_id, row.chat.tg_chat_id)
                self._cache[key] = _CachedUserRole(
                    id=row.id,
                    tg_user_id=row.user.tg_user_id,
                    user_id=row.user_id,  # type: ignore
                    tg_chat_id=row.chat.tg_chat_id,
                    chat_id=row.chat_id,  # type: ignore
                    level=row.level,
                    assigned_by_tg=(
                        row.assigned_by.tg_user_id if row.assigned_by else None
                    ),
                    assigned_by_id=(
                        row.assigned_by_id if hasattr(row, "assigned_by_id") else None  # type: ignore
                    ),
                    assigned_at=row.assigned_at,
                )
        await super().initialize()

    async def _ensure_cached(
        self,
        tg_user_id: int,
        tg_chat_id: int,
        initial_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        key = _make_cache_key(tg_user_id, tg_chat_id)
        async with self._lock:
            if key in self._cache:
                return False

        defaults = initial_data or {}
        model, created = await self.repo.ensure_record(
            tg_user_id, tg_chat_id, defaults=defaults
        )

        user = await User.get(id=model.user_id)  # type: ignore
        chat = await Chat.get(id=model.chat_id)  # type: ignore

        assigned_by_tg = None
        if getattr(model, "assigned_by_id", None):
            assigned_by = await User.filter(id=model.assigned_by_id).first()  # type: ignore
            assigned_by_tg = assigned_by.tg_user_id if assigned_by else None

        async with self._lock:
            self._cache[key] = _CachedUserRole(
                id=model.id,
                tg_user_id=user.tg_user_id,
                user_id=model.user_id,  # type: ignore
                tg_chat_id=chat.tg_chat_id,
                chat_id=model.chat_id,  # type: ignore
                level=model.level,
                assigned_by_tg=assigned_by_tg,
                assigned_by_id=getattr(model, "assigned_by_id", None),  # type: ignore
                assigned_at=model.assigned_at,
            )
        return created

    @overload
    async def get(self, cache_key: CacheKey) -> Any: ...
    @overload
    async def get(self, cache_key: CacheKey, fields: str) -> Any: ...
    @overload
    async def get(
        self, cache_key: CacheKey, fields: Sequence[str]
    ) -> Tuple[Any, ...]: ...

    async def get(
        self, cache_key: CacheKey, fields: Optional[Union[str, Sequence[str]]] = None
    ) -> _CachedUserRole | None | Any | Tuple[Any | None]:
        async with self._lock:
            obj = self._cache.get(cache_key)

        if fields is None:
            return obj
        if isinstance(fields, str):
            if obj is None:
                return None
            return getattr(obj, fields, None)
        else:
            if obj is None:
                return tuple([None for _ in fields])
            return tuple([getattr(obj, f, None) for f in fields])

    async def add_role(
        self,
        tg_user_id: int,
        tg_chat_id: int,
        level: enums.Role,
        assigned_by_tg: Optional[int] = None,
    ):
        await self._ensure_cached(
            tg_user_id, tg_chat_id, {"level": level, "assigned_by_id": None}
        )
        key = _make_cache_key(tg_user_id, tg_chat_id)
        async with self._lock:
            r = self._cache[key]
            if r.level == level:
                return
            r.level = level
        if assigned_by_tg is not None:
            assigned_by, _ = await self.repo.ensure_user(assigned_by_tg)
            async with self._lock:
                r.assigned_by_tg = assigned_by.tg_user_id
                r.assigned_by_id = assigned_by.id
                self._dirty.add(key)

    async def remove_role(self, tg_user_id: int, tg_chat_id: int):
        key = _make_cache_key(tg_user_id, tg_chat_id)
        role = None
        async with self._lock:
            if key in self._cache:
                role = self._cache[key]
                self._dirty.discard(key)
                del self._cache[key]
        await self.repo.delete_record(tg_user_id, tg_chat_id)
        return role.level if role else None

    async def get_user_roles(self, tg_user_id: int) -> List[_CachedUserRole]:
        async with self._lock:
            return [
                copy.deepcopy(v) for k, v in self._cache.items() if k[0] == tg_user_id
            ]

    async def get_chat_roles(self, tg_chat_id: int) -> List[_CachedUserRole]:
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
                key: copy.deepcopy(self._cache[key])
                for key in dirty_snapshot
                if key in self._cache
            }

        if not payloads:
            return

        items = list(payloads.items())

        try:
            tg_users = {key[0] for key in payloads.keys()}
            existing_rows = await UserRole.filter(
                user__tg_user_id__in=list(tg_users)
            ).prefetch_related("user", "assigned_by", "chat")
            existing_map = {
                (row.user.tg_user_id, row.chat.tg_chat_id): row
                for row in existing_rows
                if row.user and row.chat
            }

            to_update = []
            to_create = []
            keys_skipped_due_to_missing_fk = set()

            for key, cached in items:
                if key in existing_map:
                    row = existing_map[key]
                    dirty = False
                    if row.level != cached.level:
                        row.level = cached.level
                        dirty = True
                    if getattr(row, "assigned_by_id", None) != cached.assigned_by_id:
                        row.assigned_by_id = cached.assigned_by_id
                        dirty = True
                    if dirty:
                        to_update.append(row)
                else:
                    if cached.user_id is None:
                        user = await User.filter(tg_user_id=cached.tg_user_id).first()
                        if user:
                            cached.user_id = user.id
                    if cached.chat_id is None:
                        chat = await Chat.filter(tg_chat_id=cached.tg_chat_id).first()
                        if chat:
                            cached.chat_id = chat.id

                    if cached.user_id is None or cached.chat_id is None:
                        keys_skipped_due_to_missing_fk.add(key)
                        continue

                    to_create.append(
                        UserRole(
                            user_id=cached.user_id,
                            chat_id=cached.chat_id,
                            level=cached.level,
                            assigned_by_id=cached.assigned_by_id,
                        )
                    )

            async with in_transaction():
                if to_update:
                    await UserRole.bulk_update(
                        to_update,
                        fields=["level", "assigned_by_id"],
                        batch_size=batch_size,
                    )
                if to_create:
                    await UserRole.bulk_create(to_create, batch_size=batch_size)

        except Exception:
            from loguru import logger

            logger.exception("UserRole sync failed")
            return

        async with self._lock:
            for key, old_val in payloads.items():
                if key in keys_skipped_due_to_missing_fk:
                    continue
                cur = self._cache.get(key)
                if cur is None:
                    self._dirty.discard(key)
                    continue

                fields_old = {
                    "level": old_val.level,
                    "assigned_by_id": getattr(old_val, "assigned_by_id", None),
                }
                fields_cur = {
                    "level": cur.level,
                    "assigned_by_id": getattr(cur, "assigned_by_id", None),
                }
                if fields_old == fields_cur:
                    self._dirty.discard(key)


class UserRoleManager(BaseManager):
    def __init__(self):
        super().__init__()
        self._cache: Cache = {}
        self.repo = UserRoleRepository(self._lock)
        self.cache = UserRoleCache(self._lock, self.repo, self._cache)

        self.add_role = self.cache.add_role
        self.remove_role = self.cache.remove_role
        self.get = self.cache.get
        self.get_user_roles = self.cache.get_user_roles
        self.get_chat_roles = self.cache.get_chat_roles

    def make_cache_key(self, tg_user_id, tg_chat_id) -> CacheKey:
        return _make_cache_key(tg_user_id, tg_chat_id)

    async def chat_activation(self, tg_user_id: int, tg_chat_id: int) -> bool:
        if tg_user_id not in settings.ADMIN_TELEGRAM_IDS:
            return False
        await self.add_role(tg_user_id, tg_chat_id, enums.Role.admin)
        return True

    async def user_has_rights(
        self, tg_user_id: int, tg_chat_id: int, min_level: enums.Role
    ) -> bool:
        user_role = (
            await self.get(_make_cache_key(tg_user_id, tg_chat_id), "level")
        ) or enums.Role.user
        return user_role >= min_level

    async def get_user_chats(
        self, tg_user_id: int, min_role: enums.Role = enums.Role.moderator
    ) -> List[int]:
        roles = await self.get_user_roles(tg_user_id)
        return [r.tg_chat_id for r in roles if r.level >= min_role]
