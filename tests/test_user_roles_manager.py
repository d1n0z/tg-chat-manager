import asyncio

import pytest
import pytest_asyncio
from tortoise import Tortoise
from tortoise.exceptions import DoesNotExist

from src.core.managers.user_roles import UserRoleManager, _CachedUserRole, _make_cache_key
from src.core.models import User, Chat, UserRole
from src.core import enums

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def init_db():
    # Инициализация in-memory SQLite и генерация схем
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["src.core.models"]})
    await Tortoise.generate_schemas()
    yield
    try:
        await Tortoise._drop_databases()
    except Exception:
        pass
    await Tortoise.close_connections()


@pytest_asyncio.fixture
async def manager(init_db):
    mgr = UserRoleManager()
    # инициализируем (загрузит существующие роли если будут)
    await mgr.initialize()
    yield mgr


# Фабрики для тестов
async def create_user(tg_user_id: int, username: str | None = None):
    return await User.create(tg_user_id=tg_user_id, username=username)


async def create_chat(tg_chat_id: int, title: str | None = None):
    return await Chat.create(tg_chat_id=tg_chat_id, title=title, chat_type="group")


async def create_role_db(user: User, chat: Chat, level=enums.Role.user, assigned_by: User | None = None):
    kwargs = {"user_id": user.id, "chat_id": chat.id, "level": level}
    if assigned_by:
        kwargs["assigned_by_id"] = assigned_by.id
    return await UserRole.create(**kwargs)


# --- Тесты ---

async def test_initialize_loads_roles(init_db):
    u = await create_user(1010, "u1")
    ch = await create_chat(2010, "chat1")
    await create_role_db(u, ch, enums.Role.moderator)

    mgr = UserRoleManager()
    await mgr.initialize()

    roles = await mgr.get_user_roles(1010)
    assert roles, "roles must be loaded"
    assert any(r.level == enums.Role.moderator for r in roles)


async def test_add_role_creates_and_caches(manager):
    tg_user = 2000
    tg_chat = 3000

    # никого нет в БД — add_role должен создать User, Chat и UserRole (через ensure_record)
    await manager.add_role(tg_user, tg_chat, enums.Role.admin, assigned_by_tg=None)

    # запись в кэше обязана появиться
    cached = await manager.get(_make_cache_key(tg_user, tg_chat))
    assert isinstance(cached, _CachedUserRole)
    assert cached.tg_user_id == tg_user
    assert cached.tg_chat_id == tg_chat
    assert cached.level == enums.Role.admin

    # persist
    await manager.cache.sync()

    row = await UserRole.filter(user__tg_user_id=tg_user, chat__tg_chat_id=tg_chat).first()
    assert row is not None
    assert row.level == enums.Role.admin


async def test_add_role_idempotent(manager):
    tg_user = 2100
    tg_chat = 3100

    await manager.add_role(tg_user, tg_chat, enums.Role.user)
    await manager.add_role(tg_user, tg_chat, enums.Role.user)
    await manager.cache.sync()

    rows = await UserRole.filter(user__tg_user_id=tg_user, chat__tg_chat_id=tg_chat).all()
    assert len(rows) == 1


async def test_remove_role(manager):
    tg_user = 2200
    tg_chat = 3200

    await manager.add_role(tg_user, tg_chat, enums.Role.user)
    await manager.cache.sync()

    # убедимся, что роль в DB
    assert await UserRole.filter(user__tg_user_id=tg_user, chat__tg_chat_id=tg_chat).first() is not None

    # remove via manager
    await manager.remove_role(tg_user, tg_chat)

    # проверим удаление в DB и в кэше
    assert await UserRole.filter(user__tg_user_id=tg_user, chat__tg_chat_id=tg_chat).first() is None
    assert await manager.get(_make_cache_key(tg_user, tg_chat)) is None


async def test_edit_role_and_sync(manager):
    tg_user = 2300
    tg_chat = 3300

    await manager.add_role(tg_user, tg_chat, enums.Role.user)
    await manager.cache.sync()

    # change level
    await manager.add_role(tg_user, tg_chat, enums.Role.admin)
    await manager.cache.sync()

    row = await UserRole.filter(user__tg_user_id=tg_user, chat__tg_chat_id=tg_chat).first()
    assert row is not None and row.level == enums.Role.admin


async def test_get_chat_roles(manager):
    base_chat = 3400
    users = [4001, 4002, 4003]
    for u in users:
        await manager.add_role(u, base_chat, enums.Role.user)
    await manager.cache.sync()

    chat_roles = await manager.get_chat_roles(base_chat)
    assert len(chat_roles) >= len(users)
    assert all(isinstance(r, _CachedUserRole) for r in chat_roles)


async def test_user_has_rights_helper(manager):
    tg_user = 2500
    tg_chat = 3500

    await manager.add_role(tg_user, tg_chat, enums.Role.moderator)
    await manager.cache.sync()

    assert await manager.user_has_rights(tg_user, tg_chat, enums.Role.user)
    assert await manager.user_has_rights(tg_user, tg_chat, enums.Role.moderator)
    assert not await manager.user_has_rights(tg_user, tg_chat, enums.Role.admin)


async def test_assigned_by_creates_user_and_records(manager):
    tg_user = 2600
    tg_chat = 3600
    assigner = 2700

    # ensure assigner does not exist initially
    with pytest.raises(DoesNotExist):
        await User.get(tg_user_id=assigner)

    await manager.add_role(tg_user, tg_chat, enums.Role.user, assigned_by_tg=assigner)
    await manager.cache.sync()

    # assigned_by user must be created
    ass_user = await User.get(tg_user_id=assigner)
    assert ass_user is not None

    row = await UserRole.filter(user__tg_user_id=tg_user, chat__tg_chat_id=tg_chat).first()
    assert hasattr(row, "assigned_by_id") and row.assigned_by_id is not None  # type: ignore


async def test_concurrent_adds(manager):
    tg_chat = 3700

    async def add_user(i):
        await manager.add_role(50000 + i, tg_chat, enums.Role.user)

    await asyncio.gather(*[add_user(i) for i in range(20)])
    await manager.cache.sync()

    rows = await UserRole.filter(chat__tg_chat_id=tg_chat).all()
    # should have at least 20 created roles (could be more if DB had rows)
    assert len(rows) >= 20


async def test_no_role_returns_min_rights(manager):
    # random user/chat with no role
    assert not await manager.user_has_rights(999999, 999999, enums.Role.moderator)


async def test_get_fields(manager):
    tg_user = 3800
    tg_chat = 4800
    await manager.add_role(tg_user, tg_chat, enums.Role.admin)
    key = _make_cache_key(tg_user, tg_chat)
    level = await manager.get(key, "level")
    assert level == enums.Role.admin
    level, tg_user_id = await manager.get(key, ["level", "tg_user_id"])
    assert level == enums.Role.admin and tg_user_id == tg_user


async def test_get_user_roles_empty(manager):
    roles = await manager.get_user_roles(99999)
    assert roles == []


async def test_get_chat_roles_empty(manager):
    roles = await manager.get_chat_roles(99999)
    assert roles == []


async def test_remove_nonexistent_role(manager):
    await manager.remove_role(99999, 88888)
    assert await manager.get(_make_cache_key(99999, 88888)) is None


async def test_multiple_roles_same_user(manager):
    tg_user = 5000
    chats = [6001, 6002, 6003]
    for chat in chats:
        await manager.add_role(tg_user, chat, enums.Role.user)
    roles = await manager.get_user_roles(tg_user)
    assert len(roles) >= len(chats)
    chat_ids = {r.tg_chat_id for r in roles}
    assert all(c in chat_ids for c in chats)
