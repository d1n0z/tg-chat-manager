import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.message_pins import MessagePinManager
from src.core.models import MessagePin, Chat, User

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
    mgr = MessagePinManager()
    await mgr.initialize()
    yield mgr


async def create_chat(tg_chat_id=1):
    return await Chat.create(tg_chat_id=tg_chat_id, chat_type="group")


async def create_user(tg_user_id=42):
    return await User.create(tg_user_id=tg_user_id)


async def test_add_and_remove_pin_and_sync(manager):
    ch = await create_chat(1234)
    u = await create_user(77)

    await manager.add_pin(ch.tg_chat_id, 9999, u.tg_user_id)
    pins = await manager.get_chat_pins(ch.tg_chat_id)
    assert any(p.message_id == 9999 for p in pins)

    await manager.cache.sync()
    assert await MessagePin.filter(chat_id=ch.id, message_id=9999).exists()

    await manager.remove_pin(ch.tg_chat_id, 9999)
    assert not await MessagePin.filter(chat_id=ch.id, message_id=9999).exists()
    assert await manager.get_chat_pins(ch.tg_chat_id) == []
