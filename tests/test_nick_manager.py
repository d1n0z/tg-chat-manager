import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.nicks import NickManager, _make_cache_key
from src.core.models import Chat, Nick, User


@pytest_asyncio.fixture
async def init_db():
    await Tortoise.init(
        db_url="sqlite://:memory:", modules={"models": ["src.core.models"]}
    )
    await Tortoise.generate_schemas()
    yield
    try:
        await Tortoise._drop_databases()
    except Exception:
        pass
    await Tortoise.close_connections()


@pytest_asyncio.fixture
async def manager(init_db):
    mgr = NickManager()
    await mgr.initialize()
    yield mgr


@pytest.mark.asyncio
async def test_add_and_get_nick(manager):
    await manager.cache.initialize()

    user = await User.create(tg_user_id=1001)
    chat = await Chat.create(tg_chat_id=1001, chat_type="group")

    await manager.add_nick(user.tg_user_id, chat.tg_chat_id, "TestNick")

    cached = await manager.get(_make_cache_key(user.tg_user_id, chat.tg_chat_id))
    assert cached is not None
    assert cached.nick == "TestNick"

    assert await manager.user_has_nick(user.tg_user_id, chat.tg_chat_id) is True


@pytest.mark.asyncio
async def test_remove_nick(manager):
    await manager.cache.initialize()

    user = await User.create(tg_user_id=1002)
    chat = await Chat.create(tg_chat_id=1002, chat_type="group")

    await manager.add_nick(user.tg_user_id, chat.tg_chat_id, "NickToRemove")
    await manager.remove_nick(user.tg_user_id, chat.tg_chat_id)

    cached = await manager.get(_make_cache_key(user.tg_user_id, chat.tg_chat_id))
    assert cached is None

    db_nick = await Nick.filter(user_id=user.id, chat_id=chat.id).first()
    assert db_nick is None


@pytest.mark.asyncio
async def test_get_user_and_chat_nicks(manager):
    await manager.cache.initialize()

    user1 = await User.create(tg_user_id=2001)
    user2 = await User.create(tg_user_id=2002)
    chat1 = await Chat.create(tg_chat_id=2001, chat_type="group")
    chat2 = await Chat.create(tg_chat_id=2002, chat_type="group")

    await manager.add_nick(user1.tg_user_id, chat1.tg_chat_id, "Nick1")
    await manager.add_nick(user1.tg_user_id, chat2.tg_chat_id, "Nick2")
    await manager.add_nick(user2.tg_user_id, chat1.tg_chat_id, "Nick3")

    user1_nicks = await manager.get_user_nicks(user1.tg_user_id)
    assert len(user1_nicks) == 2
    assert {n.nick for n in user1_nicks} == {"Nick1", "Nick2"}

    chat1_nicks = await manager.get_chat_nicks(chat1.tg_chat_id)
    assert len(chat1_nicks) == 2
    assert {n.nick for n in chat1_nicks} == {"Nick1", "Nick3"}


@pytest.mark.asyncio
async def test_sync_updates_db(manager):
    await manager.cache.initialize()

    user = await User.create(tg_user_id=3001)
    chat = await Chat.create(tg_chat_id=3001, chat_type="group")

    await manager.add_nick(user.tg_user_id, chat.tg_chat_id, "OldNick")
    await manager.cache.sync()

    db_nick = await Nick.filter(user_id=user.id, chat_id=chat.id).first()
    assert db_nick is not None and db_nick.nick == "OldNick"


@pytest.mark.asyncio
async def test_add_nick_with_creator(manager):
    await manager.cache.initialize()
    user = await User.create(tg_user_id=4001)
    creator = await User.create(tg_user_id=4002)
    chat = await Chat.create(tg_chat_id=4001, chat_type="group")
    await manager.add_nick(user.tg_user_id, chat.tg_chat_id, "NickWithCreator", creator.tg_user_id)
    cached = await manager.get(_make_cache_key(user.tg_user_id, chat.tg_chat_id))
    assert cached.created_by_tg_id == creator.tg_user_id


@pytest.mark.asyncio
async def test_get_fields(manager):
    await manager.cache.initialize()
    user = await User.create(tg_user_id=5001)
    chat = await Chat.create(tg_chat_id=5001, chat_type="group")
    await manager.add_nick(user.tg_user_id, chat.tg_chat_id, "TestNick")
    key = _make_cache_key(user.tg_user_id, chat.tg_chat_id)
    nick = await manager.get(key, "nick")
    assert nick == "TestNick"
    nick, tg_user_id = await manager.get(key, ["nick", "tg_user_id"])
    assert nick == "TestNick" and tg_user_id == user.tg_user_id


@pytest.mark.asyncio
async def test_user_has_nick_false(manager):
    await manager.cache.initialize()
    assert await manager.user_has_nick(99999, 99999) is False


@pytest.mark.asyncio
async def test_get_user_nicks_empty(manager):
    await manager.cache.initialize()
    nicks = await manager.get_user_nicks(99999)
    assert nicks == []


@pytest.mark.asyncio
async def test_get_chat_nicks_empty(manager):
    await manager.cache.initialize()
    nicks = await manager.get_chat_nicks(99999)
    assert nicks == []
