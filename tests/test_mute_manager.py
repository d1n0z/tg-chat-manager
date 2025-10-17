import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.mute import MuteManager, _CachedMute
from src.core.models import Mute, User, Chat

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
    mgr = MuteManager()
    await mgr.initialize()
    yield mgr


async def create_user(tg_user_id=10):
    return await User.create(tg_user_id=tg_user_id)


async def create_chat(tg_chat_id=20):
    return await Chat.create(tg_chat_id=tg_chat_id, chat_type="group")


async def test_initialize_loads_existing_mutes(init_db):
    u = await create_user(1)
    c = await create_chat(2)
    await Mute.create(user=u, chat=c, reason="test")
    mgr = MuteManager()
    await mgr.initialize()

    res = await mgr.get_user_mutes(u.tg_user_id)
    assert isinstance(res, list) and any(r.reason == "test" for r in res)

    res2 = await mgr.get_chat_mutes(c.tg_chat_id)
    assert isinstance(res2, list) and any(r.reason == "test" for r in res2)


async def test_add_and_remove_mute_and_sync(manager, init_db):
    u = await User.create(tg_user_id=11)
    c = await Chat.create(tg_chat_id=21, chat_type="group")

    await manager.add_mute(u.tg_user_id, c.tg_chat_id, reason="spamming", active=True, auto_unmute=False)

    cached = (await manager.get_user_mutes(u.tg_user_id))[0]
    assert isinstance(cached, _CachedMute)
    assert cached.reason == "spamming"

    await manager.cache.sync()
    db = await Mute.filter(user__tg_user_id=u.tg_user_id, chat__tg_chat_id=c.tg_chat_id).first()
    assert db is not None
    assert db.reason == "spamming"

    await manager.remove_mute(u.tg_user_id, c.tg_chat_id)

    assert (await manager.get_user_mutes(u.tg_user_id)) == []
    assert await Mute.filter(user__tg_user_id=u.tg_user_id, chat__tg_chat_id=c.tg_chat_id).first() is None


async def test_remove_nonexistent_does_not_raise(manager):
    await manager.remove_mute(9999, 8888)


async def test_get_chat_mutes_empty(manager):
    result = await manager.get_chat_mutes(99999)
    assert result == []


async def test_get_user_mutes_empty(manager):
    result = await manager.get_user_mutes(99999)
    assert result == []


async def test_add_multiple_mutes_same_user(manager, init_db):
    u = await User.create(tg_user_id=50)
    c1 = await Chat.create(tg_chat_id=60, chat_type="group")
    c2 = await Chat.create(tg_chat_id=61, chat_type="group")
    await manager.add_mute(u.tg_user_id, c1.tg_chat_id, reason="spam1")
    await manager.add_mute(u.tg_user_id, c2.tg_chat_id, reason="spam2")
    mutes = await manager.get_user_mutes(u.tg_user_id)
    assert len(mutes) == 2
    reasons = {m.reason for m in mutes}
    assert "spam1" in reasons and "spam2" in reasons


async def test_edit_mute_fields(manager, init_db):
    u = await User.create(tg_user_id=70)
    c = await Chat.create(tg_chat_id=80, chat_type="group")
    await manager.add_mute(u.tg_user_id, c.tg_chat_id, reason="old", active=True)
    mutes = await manager.get_user_mutes(u.tg_user_id)
    mute = mutes[0]
    assert mute.reason == "old"
    assert mute.active is True
