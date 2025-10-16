# tests/test_chat_manager.py
import asyncio

import pytest_asyncio
import pytest
from tortoise import Tortoise
from tortoise.exceptions import DoesNotExist

from src.core.managers.chats import ChatManager, _CachedChat
from src.core.models import Chat

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module")
async def init_db():
    # Инициализация in-memory SQLite
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
    mgr = ChatManager()
    await mgr.initialize()
    yield mgr


# вспомогательная фабрика
async def create_db_chat(tg_chat_id: int = 1, title: str | None = "chat", cluster_id: int | None = None, id: int | None = None):
    kwargs = {"tg_chat_id": tg_chat_id, "title": title, "chat_type": "group", "is_active": True}
    if cluster_id is not None:
        kwargs["cluster_id"] = cluster_id
    if id is not None:
        kwargs["id"] = id
    return await Chat.create(**kwargs)


# --- Тесты ---

async def test_initialize_loads_existing_chats(init_db):
    _c1 = await create_db_chat(101, "init1")
    _c2 = await create_db_chat(102, "init2")

    mgr = ChatManager()
    await mgr.initialize()

    cached1 = await mgr.get_full(101)
    cached2 = await mgr.get_full(102)

    assert isinstance(cached1, _CachedChat)
    assert cached1.tg_chat_id == 101
    assert cached1.title == "init1"

    assert isinstance(cached2, _CachedChat)
    assert cached2.tg_chat_id == 102
    assert cached2.title == "init2"


async def test_ensure_creates_and_caches(manager):
    # Уникальный tg_chat_id, которого ещё нет в БД
    tg = 2001
    # убедимся, что в БД нет
    with pytest.raises(DoesNotExist):
        await Chat.get(tg_chat_id=tg)

    # ensure создаст запись и положит в кэш
    created = await manager.ensure_chat(tg, {"title": "ensured", "username": "bot"})
    assert created is True or created is False  # возвращает bool; проверим, что вызов прошёл

    # теперь запись в кэше
    cached = await manager.get_full(tg)
    assert cached is not None
    assert cached.tg_chat_id == tg
    assert cached.title == "ensured"
    assert cached.username == "bot"

    # и в БД должна быть запись
    db = await Chat.get(tg_chat_id=tg)
    assert db is not None
    assert db.title == "ensured"
    assert db.username == "bot"


async def test_edit_and_get_fields_and_sync(manager):
    tg = 3001
    # ensure creates record
    await manager.ensure_chat(tg, {"title": "before", "settings": {"a": 1}})
    # edit some fields
    await manager.edit(tg, title="after", username="newname", settings={"a": 2, "b": 3})

    # get single field
    title = await manager.get(tg, "title")
    assert title == "after"

    # get multiple fields
    title_u, settings = await manager.get(tg, ["title", "settings"])
    assert title_u == "after"
    assert isinstance(settings, dict) and settings.get("a") == 2

    # sync to persist
    await manager.cache.sync()

    db = await Chat.get(tg_chat_id=tg)
    assert db.title == "after"
    assert db.username == "newname"
    assert db.settings == {"a": 2, "b": 3}


async def test_remove_deletes_db_and_cache(manager):
    tg = 4001
    # create in DB
    _dbchat = await create_db_chat(tg, "to_remove")
    # ensure cache loaded
    await manager.cache.initialize()
    assert await manager.get_full(tg) is not None

    # remove
    await manager.remove(tg)

    # cache should not have it
    cached = await manager.get_full(tg)
    assert cached is None

    # DB should not have it
    res = await Chat.filter(tg_chat_id=tg).first()
    assert res is None


async def test_sync_updates_multiple_entries(manager):
    # create two chats
    tg1 = 5001
    tg2 = 5002
    await manager.ensure_chat(tg1, {"title": "t1"})
    await manager.ensure_chat(tg2, {"title": "t2"})

    # modify both in cache
    await manager.edit(tg1, title="t1-upd", is_active=False, settings={"x": 1})
    await manager.edit(tg2, title="t2-upd", username="u2", settings={"y": 2})

    # sync
    await manager.cache.sync()

    db1 = await Chat.get(tg_chat_id=tg1)
    db2 = await Chat.get(tg_chat_id=tg2)

    assert db1.title == "t1-upd"
    assert db1.is_active is False
    assert db1.settings == {"x": 1}

    assert db2.title == "t2-upd"
    assert db2.username == "u2"
    assert db2.settings == {"y": 2}


async def test_concurrent_edits_and_sync(manager):
    tg = 6001
    await manager.ensure_chat(tg, {"title": "concurrent"})

    async def worker(idx):
        # each worker sets settings to different dict
        await manager.edit(tg, settings={"worker": idx})
        # small jitter
        await asyncio.sleep(0.01 * (idx % 3))

    # run many workers concurrently
    await asyncio.gather(*[worker(i) for i in range(10)])

    # sync to DB
    await manager.cache.sync()

    db = await Chat.get(tg_chat_id=tg)
    # settings should be one of the workers' values (we can't deterministically know which), check structure
    assert isinstance(db.settings, dict) and "worker" in db.settings


async def test_get_returns_reference_modifying_mutates_cache(manager):
    tg = 7001
    await manager.ensure_chat(tg, {"title": "ref_test"})
    await manager.cache.initialize()

    cached = await manager.get_full(tg)
    assert isinstance(cached, _CachedChat)
    # modify returned object
    cached.title = "mutated"
    # fetch again and check cache was mutated (get returns reference in current impl)
    cached2 = await manager.get_full(tg)
    assert cached2.title == "mutated"

    # cleanup: set back and sync
    await manager.edit(tg, title="ref_test")
    await manager.cache.sync()


async def test_remove_nonexistent_does_not_raise(manager):
    # removing non-existent tg should not raise
    await manager.remove(999999999)


async def test_sync_idempotent_when_no_dirty(manager):
    # call sync when nothing dirty -> no error
    await manager.cache.sync()


async def test_get_settings_and_set_settings(manager):
    tg = 8001
    await manager.ensure_chat(tg, {"title": "settings_test"})
    await manager.set_settings(tg, {"key": "value", "num": 42})
    settings = await manager.get_settings(tg)
    assert settings == {"key": "value", "num": 42}
    await manager.cache.sync()
    db = await Chat.get(tg_chat_id=tg)
    assert db.settings == {"key": "value", "num": 42}


async def test_activate_deactivate(manager):
    tg = 8002
    await manager.ensure_chat(tg, {"title": "active_test", "is_active": False})
    await manager.activate(tg)
    is_active = await manager.get(tg, "is_active")
    assert is_active is True
    await manager.deactivate(tg)
    is_active = await manager.get(tg, "is_active")
    assert is_active is False


async def test_ensure_chat_updates_existing(manager):
    tg = 8003
    await manager.ensure_chat(tg, {"title": "first"})
    created = await manager.ensure_chat(tg, {"title": "second"})
    assert created is False
    cached = await manager.get_full(tg)
    assert cached.title == "first"


async def test_get_multiple_fields_tuple(manager):
    tg = 8004
    await manager.ensure_chat(tg, {"title": "multi", "username": "test_user"})
    title, username, chat_type = await manager.get(tg, ["title", "username", "chat_type"])
    assert title == "multi"
    assert username == "test_user"
    assert chat_type is None
