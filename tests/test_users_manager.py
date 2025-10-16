# tests/test_user_manager.py
import asyncio

import pytest
import pytest_asyncio
from tortoise import Tortoise
from tortoise.exceptions import DoesNotExist

from src.core.managers.users import UserManager, _CachedUser
from src.core.models import User  # Tortoise модель

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module")
async def init_db():
    """Инициализация in-memory SQLite и создание схем."""
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
    mgr = UserManager()
    await mgr.initialize()
    yield mgr


# вспомогательная фабрика для DB-пользователя
async def create_db_user(tg_user_id: int = 1, username: str | None = "u", first_name: str | None = "fn", last_name: str | None = "ln", id: int | None = None):
    kwargs = {"tg_user_id": tg_user_id, "username": username, "first_name": first_name, "last_name": last_name, "is_bot": False}
    if id is not None:
        kwargs["id"] = id
    return await User.create(**kwargs)


# --- Тесты ---

async def test_initialize_loads_existing_users(init_db):
    _u1 = await create_db_user(1001, username="u1", first_name="Alice", last_name="A")
    _u2 = await create_db_user(1002, username="u2", first_name="Bob", last_name="B")

    mgr = UserManager()
    await mgr.initialize()

    cached1 = await mgr.get(1001)
    cached2 = await mgr.get(1002)

    assert isinstance(cached1, _CachedUser)
    assert cached1.tg_user_id == 1001
    assert cached1.username == "u1"

    assert isinstance(cached2, _CachedUser)
    assert cached2.tg_user_id == 1002
    assert cached2.first_name == "Bob"


async def test_ensure_creates_and_caches(manager):
    tg = 2001
    # убедимся, что в БД нет
    with pytest.raises(DoesNotExist):
        await User.get(tg_user_id=tg)

    created = await manager.ensure_user(tg, {"username": "ensured", "first_name": "Ens"})
    assert isinstance(created, bool)

    cached = await manager.get(tg)
    assert cached is not None
    assert cached.username == "ensured"
    assert cached.first_name == "Ens"

    db = await User.get(tg_user_id=tg)
    assert db.username == "ensured"
    assert db.first_name == "Ens"


async def test_edit_get_fields_and_sync(manager):
    tg = 3001
    await manager.ensure_user(tg, {"username": "before", "meta": {"x": 1}})
    await manager.edit(tg, username="after", last_name="LN", meta={"x": 2})

    uname = await manager.get(tg, "username")
    assert uname == "after"

    uname, meta = await manager.get(tg, ("username", "meta"))
    assert uname == "after" and meta == {"x": 2}

    # persist
    await manager.cache.sync()

    db = await User.get(tg_user_id=tg)
    assert db.username == "after"
    assert db.last_name == "LN"
    assert db.meta == {"x": 2}


async def test_get_name_helper(manager):
    tg = 4001
    await manager.ensure_user(tg, {"first_name": "John", "last_name": "Doe"})
    name = await manager.get_name(tg)
    assert name == "John Doe"

    # partial
    tg2 = 4002
    await manager.ensure_user(tg2, {"first_name": "Single"})
    name2 = await manager.get_name(tg2)
    assert name2 == "Single"


async def test_remove_deletes_db_and_cache(manager):
    tg = 5001
    await create_db_user(tg, username="toremove")
    # load into cache
    await manager.cache.initialize()
    assert await manager.get(tg) is not None

    await manager.remove(tg)
    assert await manager.get(tg) is None
    assert await User.filter(tg_user_id=tg).first() is None


async def test_concurrent_edits_and_sync(manager):
    tg = 6001
    await manager.ensure_user(tg, {"username": "concurrent"})

    async def worker(idx):
        await manager.edit(tg, meta={"worker": idx})
        await asyncio.sleep(0.01 * (idx % 4))

    await asyncio.gather(*[worker(i) for i in range(8)])
    await manager.cache.sync()

    db = await User.get(tg_user_id=tg)
    assert isinstance(db.meta, dict) and "worker" in db.meta


async def test_remove_nonexistent_does_not_raise(manager):
    # should not raise
    await manager.remove(999999999)


async def test_sync_idempotent_when_no_dirty(manager):
    # no dirty -> no errors
    await manager.cache.sync()


async def test_get_returns_reference_and_mutation_reflected(manager):
    tg = 7001
    await manager.ensure_user(tg, {"username": "refuser", "first_name": "R"})
    await manager.cache.initialize()

    cached = await manager.get(tg)
    assert isinstance(cached, _CachedUser)
    cached.username = "mut"
    cached2 = await manager.get(tg)
    assert cached2.username == "mut"

    # cleanup
    await manager.edit(tg, username="refuser")
    await manager.cache.sync()


async def test_get_name_with_no_names(manager):
    tg = 8001
    await manager.ensure_user(tg, {"first_name": None, "last_name": None})
    name = await manager.get_name(tg)
    assert name is None


async def test_ensure_user_idempotent(manager):
    tg = 8002
    created1 = await manager.ensure_user(tg, {"username": "test"})
    created2 = await manager.ensure_user(tg, {"username": "other"})
    assert isinstance(created1, bool)
    assert created2 is False
    cached = await manager.get(tg)
    assert cached.username == "test"


async def test_edit_multiple_fields_at_once(manager):
    tg = 8003
    await manager.ensure_user(tg, {"username": "old"})
    await manager.edit(tg, username="new", first_name="F", last_name="L", meta={"a": 1})
    cached = await manager.get(tg)
    assert cached.username == "new"
    assert cached.first_name == "F"
    assert cached.last_name == "L"
    assert cached.meta == {"a": 1}


async def test_get_tuple_fields(manager):
    tg = 8004
    await manager.ensure_user(tg, {"username": "u", "first_name": "F"})
    username, first_name, is_bot = await manager.get(tg, ("username", "first_name", "is_bot"))
    assert username == "u"
    assert first_name == "F"
    assert is_bot is False
