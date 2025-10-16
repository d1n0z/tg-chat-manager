import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.chat_setting import ChatSettingManager
from src.core.models import ChatSetting, Chat

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def init_db():
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
    mgr = ChatSettingManager()
    await mgr.initialize()
    yield mgr


async def create_chat(tg_chat_id=444):
    return await Chat.create(tg_chat_id=tg_chat_id, chat_type="group")


async def test_set_get_remove_and_sync(manager):
    ch = await create_chat(4444)
    await manager.set(ch.id, "theme", {"color": "blue"})
    v = await manager.get(ch.id, "theme")
    assert v == {"color": "blue"}

    # sync persists
    await manager.cache.sync()
    assert await ChatSetting.filter(chat_id=ch.id, key="theme").exists()

    await manager.remove(ch.id, "theme")
    assert await ChatSetting.filter(chat_id=ch.id, key="theme").exists() is False
    assert await manager.get(ch.id, "theme") is None


async def test_get_nonexistent_setting(manager):
    ch = await create_chat(5555)
    result = await manager.get(ch.id, "nonexistent")
    assert result is None


async def test_update_setting(manager):
    ch = await create_chat(6666)
    await manager.set(ch.id, "lang", {"code": "en"})
    await manager.set(ch.id, "lang", {"code": "ru"})
    v = await manager.get(ch.id, "lang")
    assert v == {"code": "ru"}
    await manager.cache.sync()
    db = await ChatSetting.filter(chat_id=ch.id, key="lang").first()
    assert db.value == {"code": "ru"}  # type: ignorre


async def test_multiple_settings_same_chat(manager):
    ch = await create_chat(7777)
    await manager.set(ch.id, "k1", {"v": 1})
    await manager.set(ch.id, "k2", {"v": 2})
    await manager.set(ch.id, "k3", {"v": 3})
    assert await manager.get(ch.id, "k1") == {"v": 1}
    assert await manager.get(ch.id, "k2") == {"v": 2}
    assert await manager.get(ch.id, "k3") == {"v": 3}


async def test_remove_nonexistent_setting(manager):
    ch = await create_chat(8888)
    await manager.remove(ch.id, "nonexistent")


async def test_set_complex_value(manager):
    ch = await create_chat(9999)
    complex_val = {"nested": {"data": [1, 2, 3]}, "flag": True}
    await manager.set(ch.id, "complex", complex_val)
    v = await manager.get(ch.id, "complex")
    assert v == complex_val
