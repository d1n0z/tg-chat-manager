import asyncio

import pytest
import pytest_asyncio
from tortoise import Tortoise
from tortoise.exceptions import DoesNotExist

from src.core.managers.clusters import ClusterManager
from src.core.models import Cluster, Chat

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module")
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
    mgr = ClusterManager()
    await mgr.initialize()
    yield mgr


async def make_cluster(name="CLUSTER", slug=None, is_global=False):
    obj = await Cluster.create(name=name, slug=slug, is_global=is_global)
    return obj


async def make_chat(tg_chat_id: int = 1, title: str = "chat", cluster: Cluster | None = None, id: int | None = None):
    kwargs = {"tg_chat_id": tg_chat_id, "title": title, "chat_type": "group"}
    if cluster is not None:
        kwargs["cluster_id"] = cluster.id
    if id is not None:
        kwargs["id"] = id
    chat = await Chat.create(**kwargs)
    return chat


async def test_initialize_loads_clusters_and_chats(init_db):
    c1 = await make_cluster("C1", slug="c1", is_global=False)
    c2 = await make_cluster("C2", slug="c2", is_global=False)

    await make_chat(10, title="chat1", cluster=c1)
    await make_chat(11, title="chat2", cluster=c2)

    mgr = ClusterManager()
    await mgr.initialize()

    cached_c1 = await mgr.get_cluster(c1.id)
    cached_c2 = await mgr.get_cluster(c2.id)

    assert cached_c1 is not None and 10 in cached_c1.chat_ids
    assert cached_c2 is not None and 11 in cached_c2.chat_ids


async def test_add_cluster_creates_and_caches(manager):
    cluster_obj = await manager.add_cluster("new_cluster", slug="nc", is_global=False)
    assert cluster_obj.id is not None

    cached = await manager.get_cluster(cluster_obj.id)
    assert cached is not None
    assert cached.name == "new_cluster"
    assert cached.slug == "nc"
    assert cached.chat_ids == set()


async def test_add_chat_to_existing_cluster_marks_dirty_and_sync_assigns(manager):
    c = await make_cluster("assign_test")
    ch = await make_chat(1000, title="to_assign")

    db_chat = await Chat.get(id=ch.id)
    assert db_chat.cluster_id is None  # type: ignore

    await manager.add_chat(c.id, ch.tg_chat_id)

    await manager.cache.sync()

    db_chat = await Chat.get(id=ch.id)
    assert db_chat.cluster_id == c.id  # type: ignore


async def test_remove_chat_unassigns_and_sync(manager):
    c = await make_cluster("remove_test")
    ch = await make_chat(2000, title="to_remove", cluster=c)

    await manager.cache.initialize()
    cached = await manager.get_cluster(c.id)
    assert ch.tg_chat_id in cached.chat_ids

    await manager.remove_chat(c.id, ch.tg_chat_id)
    await manager.cache.sync()

    db_chat = await Chat.get(id=ch.id)
    assert db_chat.cluster_id is None  # type: ignore


async def test_add_chat_for_nonexistent_cluster_noop(manager):
    ch = await make_chat(3000, title="no_cluster")
    await manager.add_chat(999, ch.tg_chat_id)

    await manager.cache.sync()

    db_chat = await Chat.get(id=ch.id)
    assert db_chat.cluster_id is None  # type: ignore


async def test_add_chat_for_nonexistent_chat_then_create_and_sync(manager):
    c = await make_cluster("deferred_test")
    forged_tg_chat_id = 7777

    await manager.add_chat(c.id, forged_tg_chat_id)

    await manager.cache.sync()
    with pytest.raises(DoesNotExist):
        await Chat.get(tg_chat_id=forged_tg_chat_id)

    await make_chat(forged_tg_chat_id, title="created_later")

    await manager.cache.sync()
    db_chat = await Chat.get(tg_chat_id=forged_tg_chat_id)
    assert db_chat.cluster_id == c.id  # type: ignore


async def test_concurrent_adds_and_sync(manager):
    c = await make_cluster("concurrent")
    chats = [await make_chat(5000 + i, title=f"c{i}") for i in range(20)]
    await asyncio.gather(*[manager.add_chat(c.id, ch.tg_chat_id) for ch in chats])

    cached = await manager.get_cluster(c.id)
    assert cached is not None and len(cached.chat_ids) >= 20

    await manager.cache.sync()

    db_assigned = await Chat.filter(cluster_id=c.id).all()
    assert {ch.tg_chat_id for ch in db_assigned}.issuperset({ch.tg_chat_id for ch in chats})


async def test_remove_cluster_deletes_db_and_cache(manager):
    c = await make_cluster("to_delete")
    ch1 = await make_chat(6001, title="d1", cluster=c)
    ch2 = await make_chat(6002, title="d2", cluster=c)

    await manager.cache.initialize()
    cached = await manager.get_cluster(c.id)
    assert cached is not None

    await manager.remove_cluster(c.id)

    cached_after = await manager.get_cluster(c.id)
    assert cached_after is None

    with pytest.raises(DoesNotExist):
        await Cluster.get(id=c.id)

    remaining_chats = await Chat.filter(id__in=[ch1.id, ch2.id]).all()
    assert len(remaining_chats) in (0, 2)


async def test_sync_idempotent_when_no_dirty(manager):
    await manager.cache.sync()


async def test_get_all_clusters_returns_deep_copies(manager):
    c = await make_cluster("copy_test")
    await make_chat(7001, title="copy", cluster=c)
    await manager.cache.initialize()

    all_clusters = await manager.get_all_clusters()
    assert isinstance(all_clusters, list) and all_clusters

    first = all_clusters[0]
    set(first.chat_ids)
    first.chat_ids.add(99999)
    fresh = await manager.get_cluster(first.id)
    assert 99999 not in fresh.chat_ids


async def test_get_returns_reference_modifying_mutates_cache(manager):
    c = await make_cluster("ref_test")
    await make_chat(8001, title="ref", cluster=c)
    await manager.cache.initialize()

    cached = await manager.get_cluster(c.id)
    cached.chat_ids.add(123456)
    cached2 = await manager.get_cluster(c.id)
    assert 123456 in cached2.chat_ids

    cached.chat_ids.discard(123456)
    await manager.cache.sync()


async def test_add_cluster_with_slug(manager):
    cluster = await manager.add_cluster("SlugTest", slug="slug-test", is_global=False)
    assert cluster.slug == "slug-test"
    cached = await manager.get_cluster(cluster.id)
    assert cached.slug == "slug-test"


async def test_add_cluster_global(manager):
    cluster = await manager.add_cluster("Global", is_global=True)
    assert cluster.is_global is True
    cached = await manager.get_cluster(cluster.id)
    assert cached.is_global is True


async def test_get_nonexistent_cluster(manager):
    result = await manager.get_cluster(99999)
    assert result is None


async def test_remove_nonexistent_cluster(manager):
    await manager.remove_cluster(99999)


async def test_add_multiple_chats_to_cluster(manager):
    c = await make_cluster("multi")
    chats = [await make_chat(9000 + i, title=f"ch{i}") for i in range(5)]
    for ch in chats:
        await manager.add_chat(c.id, ch.tg_chat_id)
    cached = await manager.get_cluster(c.id)
    assert len(cached.chat_ids) == 5
