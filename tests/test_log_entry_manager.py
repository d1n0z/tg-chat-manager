import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.log_entry import LogEntryManager
from src.core.models import LogEntry, Cluster, Chat, User

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
    mgr = LogEntryManager()
    await mgr.initialize()
    yield mgr


async def create_cluster(name="L"):
    return await Cluster.create(name=name)


async def create_chat(tg_chat_id=333):
    return await Chat.create(tg_chat_id=tg_chat_id, chat_type="group")


async def create_user(tg_user_id=700):
    return await User.create(tg_user_id=tg_user_id)


async def test_add_log_and_get(manager):
    cl = await create_cluster("logs")
    ch = await create_chat(3333)
    actor = await create_user(701)
    target = await create_user(702)

    await manager.add_log(cluster_id=cl.id, chat_id=ch.id, action="MUTE", target_user_id=target.id, actor_user_id=actor.id, reason="spam")
    logs = await manager.get_cluster_logs(cl.id)
    assert any(log.action == "MUTE" and log.reason == "spam" for log in logs)

    # persisted
    assert await LogEntry.filter(cluster_id=cl.id, action="MUTE").exists()
