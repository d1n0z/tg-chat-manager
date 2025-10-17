import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.global_ban import GlobalBanManager
from src.core.models import GlobalBan, User, Cluster

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
    mgr = GlobalBanManager()
    await mgr.initialize()
    yield mgr


async def create_user(tg_user_id=100):
    return await User.create(tg_user_id=tg_user_id)


async def create_cluster(name="C"):
    return await Cluster.create(name=name)


async def test_add_ban_and_get(manager):
    u = await create_user(200)
    cl = await create_cluster("testban")
    await manager.add_ban(u.tg_user_id, cl.id, reason="bad", active=True)
    res = await manager.get_user_bans(u.tg_user_id)
    assert any(b.reason == "bad" and b.cluster_id == cl.id for b in res)

    await manager.cache.sync()
    db = await GlobalBan.filter(user_id=u.id, cluster_id=cl.id).first()
    assert db is not None and db.reason == "bad"


async def test_remove_ban(manager):
    u = await create_user(201)
    cl = await create_cluster("rmban")
    await manager.add_ban(u.tg_user_id, cl.id, reason="x")
    await manager.cache.sync()
    assert await GlobalBan.filter(user_id=u.id, cluster_id=cl.id).exists()

    await manager.remove_ban(u.tg_user_id, cl.id)
    assert not await GlobalBan.filter(user_id=u.id, cluster_id=cl.id).exists()


async def test_get_cluster_bans_empty(manager):
    res = await manager.get_cluster_bans(None)
    assert isinstance(res, list)


async def test_get_user_bans_empty(manager):
    res = await manager.get_user_bans(99999)
    assert res == []


async def test_multiple_bans_same_user(manager):
    u = await create_user(300)
    cl1 = await create_cluster("ban1")
    cl2 = await create_cluster("ban2")
    await manager.add_ban(u.tg_user_id, cl1.id, reason="r1")
    await manager.add_ban(u.tg_user_id, cl2.id, reason="r2")
    bans = await manager.get_user_bans(u.tg_user_id)
    assert len(bans) == 2
    reasons = {b.reason for b in bans}
    assert "r1" in reasons and "r2" in reasons


async def test_get_cluster_bans(manager):
    u1 = await create_user(400)
    u2 = await create_user(401)
    cl = await create_cluster("shared")
    await manager.add_ban(u1.tg_user_id, cl.id, reason="a")
    await manager.add_ban(u2.tg_user_id, cl.id, reason="b")
    bans = await manager.get_cluster_bans(cl.id)
    assert len(bans) == 2


async def test_remove_nonexistent_ban(manager):
    await manager.remove_ban(99999, 88888)
