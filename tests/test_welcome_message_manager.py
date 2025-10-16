import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.welcome_messages import WelcomeMessageManager, _CachedWelcome
from src.core.models import WelcomeMessage, Cluster, User

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
    mgr = WelcomeMessageManager()
    await mgr.initialize()
    yield mgr


async def create_cluster(name="W"):
    return await Cluster.create(name=name)


async def create_user(tg_user_id=500):
    return await User.create(tg_user_id=tg_user_id)


async def test_set_get_remove_and_sync(manager):
    cl = await create_cluster("welc")
    u = await create_user(501)

    await manager.set_message(cl.id, "Hello", u.id, is_default=False)
    cached = await manager.get(cl.id)
    assert isinstance(cached, _CachedWelcome)
    assert cached.text == "Hello"

    # sync and check DB
    await manager.cache.sync()
    db = await WelcomeMessage.filter(cluster_id=cl.id).first()
    assert db is not None and db.text == "Hello"

    # remove
    await manager.remove_message(cl.id)
    assert await WelcomeMessage.filter(cluster_id=cl.id).exists() is False
    assert await manager.get(cl.id) is None


async def test_get_nonexistent(manager):
    result = await manager.get(99999)
    assert result is None


async def test_update_message(manager):
    cl = await create_cluster("upd")
    u = await create_user(502)
    await manager.set_message(cl.id, "First", u.id)
    await manager.set_message(cl.id, "Second", u.id)
    cached = await manager.get(cl.id)
    assert cached.text == "Second"
    await manager.cache.sync()
    db = await WelcomeMessage.filter(cluster_id=cl.id).first()
    assert db.text == "Second"  # type: ignore


async def test_set_default_message(manager):
    cl = await create_cluster("def")
    u = await create_user(503)
    await manager.set_message(cl.id, "Default", u.id, is_default=True)
    cached = await manager.get(cl.id)
    assert cached.is_default is True


async def test_remove_nonexistent(manager):
    await manager.remove_message(99999)
