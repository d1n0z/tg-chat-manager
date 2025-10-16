import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.nicks import NickManager, _make_cache_key
from src.core.models import Cluster, Nick, User


@pytest_asyncio.fixture
async def init_db():
    # Инициализация in-memory SQLite и генерация схем
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
    # инициализируем (загрузит существующие роли если будут)
    await mgr.initialize()
    yield mgr


@pytest.mark.asyncio
async def test_add_and_get_nick(manager):
    await manager.cache.initialize()

    # подготовка данных
    user = await User.create(tg_user_id=1001)
    cluster = await Cluster.create(name="TestCluster")

    # добавляем ник
    await manager.add_nick(user.id, cluster.id, "TestNick", created_by_id=None)

    # проверяем кэш
    cached = await manager.get(_make_cache_key(user.id, cluster.id))
    assert cached is not None
    assert cached.nick == "TestNick"

    # проверяем user_has_nick
    assert await manager.user_has_nick(user.id, cluster.id) is True


@pytest.mark.asyncio
async def test_remove_nick(manager):
    await manager.cache.initialize()

    user = await User.create(tg_user_id=1002)
    cluster = await Cluster.create(name="Cluster2")

    # добавляем ник
    await manager.add_nick(user.id, cluster.id, "NickToRemove")

    # удаляем ник
    await manager.remove_nick(user.id, cluster.id)

    # проверяем кэш
    cached = await manager.get(_make_cache_key(user.id, cluster.id))
    assert cached is None

    # проверяем базу
    db_nick = await Nick.filter(user_id=user.id, cluster_id=cluster.id).first()
    assert db_nick is None


@pytest.mark.asyncio
async def test_get_user_and_cluster_nicks(manager):
    await manager.cache.initialize()

    user1 = await User.create(tg_user_id=2001)
    user2 = await User.create(tg_user_id=2002)
    cluster1 = await Cluster.create(name="ClusterA")
    cluster2 = await Cluster.create(name="ClusterB")

    await manager.add_nick(user1.id, cluster1.id, "Nick1")
    await manager.add_nick(user1.id, cluster2.id, "Nick2")
    await manager.add_nick(user2.id, cluster1.id, "Nick3")

    user1_nicks = await manager.get_user_nicks(user1.id)
    assert len(user1_nicks) == 2
    assert {n.nick for n in user1_nicks} == {"Nick1", "Nick2"}

    cluster1_nicks = await manager.get_cluster_nicks(cluster1.id)
    assert len(cluster1_nicks) == 2
    assert {n.nick for n in cluster1_nicks} == {"Nick1", "Nick3"}


@pytest.mark.asyncio
async def test_sync_updates_db(manager):
    await manager.cache.initialize()

    user = await User.create(tg_user_id=3001)
    cluster = await Cluster.create(name="SyncCluster")

    await manager.add_nick(user.id, cluster.id, "OldNick")

    # вручную меняем ник в кэше
    key = _make_cache_key(user.id, cluster.id)
    cached = await manager.get(key)
    cached.nick = "NewNick"

    # sync
    await manager.cache.sync()

    db_nick = await Nick.filter(user_id=user.id, cluster_id=cluster.id).first()
    assert hasattr(db_nick, "nick") and db_nick.nick == "NewNick"  # type: ignore


@pytest.mark.asyncio
async def test_add_nick_with_creator(manager):
    await manager.cache.initialize()
    user = await User.create(tg_user_id=4001)
    creator = await User.create(tg_user_id=4002)
    cluster = await Cluster.create(name="CreatorCluster")
    await manager.add_nick(user.id, cluster.id, "NickWithCreator", created_by_id=creator.id)
    cached = await manager.get(_make_cache_key(user.id, cluster.id))
    assert cached.created_by_id == creator.id


@pytest.mark.asyncio
async def test_get_fields(manager):
    await manager.cache.initialize()
    user = await User.create(tg_user_id=5001)
    cluster = await Cluster.create(name="FieldCluster")
    await manager.add_nick(user.id, cluster.id, "TestNick")
    key = _make_cache_key(user.id, cluster.id)
    nick = await manager.get(key, "nick")
    assert nick == "TestNick"
    nick, user_id = await manager.get(key, ["nick", "user_id"])
    assert nick == "TestNick" and user_id == user.id


@pytest.mark.asyncio
async def test_user_has_nick_false(manager):
    await manager.cache.initialize()
    assert await manager.user_has_nick(99999, None) is False


@pytest.mark.asyncio
async def test_get_user_nicks_empty(manager):
    await manager.cache.initialize()
    nicks = await manager.get_user_nicks(99999)
    assert nicks == []


@pytest.mark.asyncio
async def test_get_cluster_nicks_empty(manager):
    await manager.cache.initialize()
    nicks = await manager.get_cluster_nicks(99999)
    assert nicks == []
