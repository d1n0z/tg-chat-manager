import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.news_broadcast import NewsBroadcastManager
from src.core.models import NewsBroadcast, Cluster, User

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
    mgr = NewsBroadcastManager()
    await mgr.initialize()
    yield mgr


async def create_cluster(name="NB"):
    return await Cluster.create(name=name)


async def create_user(tg_user_id=900):
    return await User.create(tg_user_id=tg_user_id)


async def test_add_broadcast_and_get(manager):
    cl = await create_cluster("nbc")
    u = await create_user(901)
    await manager.add_broadcast(cl.id, "hello world", u.id, meta={"x": 1})
    res = await manager.get_cluster_broadcasts(cl.id)
    assert any(b.content == "hello world" for b in res)

    # broadcast persisted (created via repository)
    assert await NewsBroadcast.filter(cluster_id=cl.id, content="hello world").exists()
