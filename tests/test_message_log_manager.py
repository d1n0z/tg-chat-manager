import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.message_logs import MessageLogManager
from src.core.models import Chat, MessageLog

pytestmark = pytest.mark.asyncio


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
    mgr = MessageLogManager()
    await mgr.initialize()
    yield mgr


async def test_add_message(manager):
    await manager.add_message(123, 1, None)
    chat = await Chat.filter(tg_chat_id=123).first()
    assert chat is not None
    log = await MessageLog.filter(chat_id=chat.id, message_id=1).first()
    assert log is not None
    assert log.message_thread_id is None


async def test_add_message_with_thread(manager):
    await manager.add_message(123, 1, 456)
    chat = await Chat.get(tg_chat_id=123)
    log = await MessageLog.get(chat_id=chat.id, message_id=1)
    assert log.message_thread_id == 456


async def test_get_last_n_messages(manager):
    for i in range(10):
        await manager.add_message(123, i + 1, None)

    messages = await manager.get_last_n_messages(123, 5, None)
    assert len(messages) == 5
    assert messages == [10, 9, 8, 7, 6]


async def test_get_last_n_messages_with_thread(manager):
    for i in range(5):
        await manager.add_message(123, i + 1, 100)
    for i in range(5):
        await manager.add_message(123, i + 6, 200)

    messages_thread_100 = await manager.get_last_n_messages(123, 3, 100)
    assert len(messages_thread_100) == 3
    assert messages_thread_100 == [5, 4, 3]

    messages_thread_200 = await manager.get_last_n_messages(123, 3, 200)
    assert len(messages_thread_200) == 3
    assert messages_thread_200 == [10, 9, 8]


async def test_get_last_n_messages_empty(manager):
    messages = await manager.get_last_n_messages(999, 5, None)
    assert messages == []
