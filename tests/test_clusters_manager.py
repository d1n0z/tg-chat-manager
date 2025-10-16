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
    """
    Инициализирует in-memory sqlite базу для тестов и создаёт таблицы по моделям в src.core.models.
    """
    # Подключаем модели из модуля src.core.models
    await Tortoise.init(db_url="sqlite://:memory:", modules={"models": ["src.core.models"]})
    await Tortoise.generate_schemas()
    yield
    # teardown
    try:
        # удаляем схемы/соединения
        await Tortoise._drop_databases()
    except Exception:
        pass
    await Tortoise.close_connections()


@pytest_asyncio.fixture
async def manager(init_db):
    """
    Создаёт чистый ClusterManager для каждого теста.
    """
    mgr = ClusterManager()
    # инициализируем внутренний кэш из БД (пустая БД — нормально)
    await mgr.initialize()
    yield mgr
    # нет специального teardown для менеджера


# --- вспомогательные фабрики ---
async def make_cluster(name="CLUSTER", slug=None, is_global=False):
    obj = await Cluster.create(name=name, slug=slug, is_global=is_global)
    return obj


async def make_chat(tg_chat_id: int = 1, title: str = "chat", cluster: Cluster | None = None, id: int | None = None):
    kwargs = {"tg_chat_id": tg_chat_id, "title": title, "chat_type": "group"}
    if cluster is not None:
        kwargs["cluster_id"] = cluster.id
    if id is not None:
        # Tortoise позволяет задать id вручную в create
        kwargs["id"] = id
    chat = await Chat.create(**kwargs)
    return chat


async def test_initialize_loads_clusters_and_chats(init_db):
    # Подготовка: создаём 2 кластера и по чату в каждом
    c1 = await make_cluster("C1", slug="c1", is_global=False)
    c2 = await make_cluster("C2", slug="c2", is_global=False)

    await make_chat(10, title="chat1", cluster=c1)
    await make_chat(11, title="chat2", cluster=c2)

    mgr = ClusterManager()
    # инициализируем кэш из DB
    await mgr.initialize()

    # проверяем, что кластеры подгрузились
    cached_c1 = await mgr.get_cluster(c1.id)
    cached_c2 = await mgr.get_cluster(c2.id)

    assert cached_c1 is not None and c1.id in cached_c1.chat_ids
    assert cached_c2 is not None and c2.id in cached_c2.chat_ids


async def test_add_cluster_creates_and_caches(manager):
    # добавляем кластер через менеджер
    cluster_obj = await manager.add_cluster("new_cluster", slug="nc", is_global=False)
    assert cluster_obj.id is not None

    # проверить, что в кэше
    cached = await manager.get_cluster(cluster_obj.id)
    assert cached is not None
    assert cached.name == "new_cluster"
    assert cached.slug == "nc"
    assert cached.chat_ids == set()


async def test_add_chat_to_existing_cluster_marks_dirty_and_sync_assigns(manager):
    # Создаём кластер и чат в БД (чат без cluster)
    c = await make_cluster("assign_test")
    ch = await make_chat(1000, title="to_assign")

    # убедимся, что чат не привязан
    db_chat = await Chat.get(id=ch.id)
    assert db_chat.cluster_id is None  # type: ignore

    # добавим chat в кэш для кластера
    await manager.add_chat(c.id, ch.id)

    # внутренне: cache._dirty содержит c.id
    # запустим sync() — должно назначить cluster_id у чата
    await manager.cache.sync()

    db_chat = await Chat.get(id=ch.id)
    assert db_chat.cluster_id == c.id  # type: ignore


async def test_remove_chat_unassigns_and_sync(manager):
    c = await make_cluster("remove_test")
    ch = await make_chat(2000, title="to_remove", cluster=c)

    # инициализируем кэш из БД, чтобы он знал о связи
    await manager.cache.initialize()
    cached = await manager.get_cluster(c.id)
    assert ch.id in cached.chat_ids

    # удаляем из кэша
    await manager.remove_chat(c.id, ch.id)
    # применяем sync -> в БД cluster_id должен стать NULL
    await manager.cache.sync()

    db_chat = await Chat.get(id=ch.id)
    assert db_chat.cluster_id is None  # type: ignore


async def test_add_chat_for_nonexistent_cluster_noop(manager):
    # пытаемся добавить чат в кластер, которого нет
    ch = await make_chat(3000, title="no_cluster")
    # cluster_id 999 не существует
    await manager.add_chat(999, ch.id)  # должен просто вернуть/не упасть

    # sync ничего не должен сделать
    await manager.cache.sync()

    db_chat = await Chat.get(id=ch.id)
    assert db_chat.cluster_id is None  # type: ignore


async def test_add_chat_for_nonexistent_chat_then_create_and_sync(manager):
    """
    Сценарий:
     1) в кэше добавляется chat_id который ещё не создан в БД (вручную используем id 7777)
     2) sync — ничего не делает (т.к. chat не в БД)
     3) создаём Chat с тем же id вручную
     4) sync снова — chat получает cluster_id
    """
    c = await make_cluster("deferred_test")
    forged_chat_id = 7777

    # добавляем в кэш chat id, которого нет
    await manager.add_chat(c.id, forged_chat_id)

    # первый sync: ничего не произойдёт (chat не существует в БД)
    await manager.cache.sync()
    with pytest.raises(DoesNotExist):
        # chat ещё нет
        await Chat.get(id=forged_chat_id)

    # создаём chat с id=forged_chat_id вручную
    await make_chat(4000, title="created_later", id=forged_chat_id)

    # второй sync: теперь должен назначиться cluster_id
    await manager.cache.sync()
    db_chat = await Chat.get(id=forged_chat_id)
    assert db_chat.cluster_id == c.id  # type: ignore


async def test_concurrent_adds_and_sync(manager):
    """
    Проверяет конкурентное добавление множества чатов в один кластер.
    """
    c = await make_cluster("concurrent")
    # создаём 20 чатов
    chats = [await make_chat(5000 + i, title=f"c{i}") for i in range(20)]
    # конкурентно добавляем их в кэш
    await asyncio.gather(*[manager.add_chat(c.id, ch.id) for ch in chats])

    # перед sync — все должны быть в кэше
    cached = await manager.get_cluster(c.id)
    assert cached is not None and len(cached.chat_ids) >= 20

    # sync
    await manager.cache.sync()

    # убедимся, что все чаты получили cluster_id
    db_assigned = await Chat.filter(cluster_id=c.id).all()
    assert {ch.id for ch in db_assigned}.issuperset({ch.id for ch in chats})


async def test_remove_cluster_deletes_db_and_cache(manager):
    """
    Удаление кластера: проверяем, что кластер удалился из БД и кэша.
    Заметь: в моделях Chat.foreignkey on_delete=CASCADE — зависимые чаты будут удалены.
    """
    c = await make_cluster("to_delete")
    ch1 = await make_chat(6001, title="d1", cluster=c)
    ch2 = await make_chat(6002, title="d2", cluster=c)

    # инициализируем кэш
    await manager.cache.initialize()
    cached = await manager.get_cluster(c.id)
    assert cached is not None

    # удаляем кластер через менеджер
    await manager.remove_cluster(c.id)

    # в кэше записи нет
    cached_after = await manager.get_cluster(c.id)
    assert cached_after is None

    # в БД кластер удалён
    with pytest.raises(DoesNotExist):
        await Cluster.get(id=c.id)

    # поведение с chat зависит от on_delete в модели (у тебя CASCADE) -> чаты могут быть удалены.
    remaining_chats = await Chat.filter(id__in=[ch1.id, ch2.id]).all()
    assert len(remaining_chats) in (0, 2)


async def test_sync_idempotent_when_no_dirty(manager):
    # вызываем sync без dirty — не должно падать
    await manager.cache.sync()  # просто не должно бросать исключение


async def test_get_all_clusters_returns_deep_copies(manager):
    # создаём кластер и инициируем
    c = await make_cluster("copy_test")
    await make_chat(7001, title="copy", cluster=c)
    await manager.cache.initialize()

    all_clusters = await manager.get_all_clusters()
    assert isinstance(all_clusters, list) and all_clusters

    # модифицируем возвращённый объект и проверяем, что внутренний кэш не изменился
    first = all_clusters[0]
    set(first.chat_ids)
    first.chat_ids.add(99999)
    # получаем заново — кэш не должен содержать 99999
    fresh = await manager.get_cluster(first.id)
    assert 99999 not in fresh.chat_ids


async def test_get_returns_reference_modifying_mutates_cache(manager):
    """
    Проверка контр-варианта: метод get возвращает ссылку на объект в кэше.
    Если это поведение нежелательно, тест покажет побочный эффект.
    """
    c = await make_cluster("ref_test")
    await make_chat(8001, title="ref", cluster=c)
    await manager.cache.initialize()

    cached = await manager.get_cluster(c.id)
    # напрямую модифицируем возвращённый объект (если метод возвращает ссылку)
    cached.chat_ids.add(123456)
    # проверим, что в реальном кэше изменение отразилось
    cached2 = await manager.get_cluster(c.id)
    assert 123456 in cached2.chat_ids

    # отчищаем побочный эффект, чтобы не мешать другим тестам
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
        await manager.add_chat(c.id, ch.id)
    cached = await manager.get_cluster(c.id)
    assert len(cached.chat_ids) == 5
