import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.cluster_setting import ClusterSettingManager
from src.core.models import ClusterSetting, Cluster

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
    mgr = ClusterSettingManager()
    await mgr.initialize()
    yield mgr


async def create_cluster(name="cfg"):
    return await Cluster.create(name=name)


async def test_set_get_remove_and_sync(manager):
    cl = await create_cluster("cfg1")
    await manager.set(cl.id, "announce", {"enabled": True})
    v = await manager.get(cl.id, "announce")
    assert v == {"enabled": True}

    await manager.cache.sync()
    assert await ClusterSetting.filter(cluster_id=cl.id, key="announce").exists()

    await manager.remove(cl.id, "announce")
    assert await ClusterSetting.filter(cluster_id=cl.id, key="announce").exists() is False
    assert await manager.get(cl.id, "announce") is None
