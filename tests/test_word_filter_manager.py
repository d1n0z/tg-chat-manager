import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.word_filter import WordFilterManager, _make_cache_key
from src.core.models import Chat, User, WordFilter


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
    mgr = WordFilterManager()
    await mgr.initialize()
    yield mgr


@pytest.mark.asyncio
async def test_add_word(manager):
    await manager.cache.initialize()

    chat = await Chat.create(tg_chat_id=1001, chat_type="group")
    user = await User.create(tg_user_id=1001)

    await manager.add_word(chat.tg_chat_id, "badword", user.tg_user_id)

    words = await manager.get_chat_words(chat.tg_chat_id)
    assert "badword" in words


@pytest.mark.asyncio
async def test_add_word_lowercase(manager):
    await manager.cache.initialize()

    chat = await Chat.create(tg_chat_id=1002, chat_type="group")

    await manager.add_word(chat.tg_chat_id, "BadWord")

    words = await manager.get_chat_words(chat.tg_chat_id)
    assert "badword" in words


@pytest.mark.asyncio
async def test_remove_word(manager):
    await manager.cache.initialize()

    chat = await Chat.create(tg_chat_id=1003, chat_type="group")

    await manager.add_word(chat.tg_chat_id, "removeword")
    await manager.remove_word(chat.tg_chat_id, "removeword")

    words = await manager.get_chat_words(chat.tg_chat_id)
    assert "removeword" not in words

    db_word = await WordFilter.filter(chat_id=chat.id, word="removeword").first()
    assert db_word is None


@pytest.mark.asyncio
async def test_get_chat_words_empty(manager):
    await manager.cache.initialize()

    words = await manager.get_chat_words(99999)
    assert words == []


@pytest.mark.asyncio
async def test_get_chat_words_multiple(manager):
    await manager.cache.initialize()

    chat = await Chat.create(tg_chat_id=1004, chat_type="group")

    await manager.add_word(chat.tg_chat_id, "word1")
    await manager.add_word(chat.tg_chat_id, "word2")
    await manager.add_word(chat.tg_chat_id, "word3")

    words = await manager.get_chat_words(chat.tg_chat_id)
    assert len(words) == 3
    assert set(words) == {"word1", "word2", "word3"}


@pytest.mark.asyncio
async def test_add_duplicate_word(manager):
    await manager.cache.initialize()

    chat = await Chat.create(tg_chat_id=1005, chat_type="group")

    await manager.add_word(chat.tg_chat_id, "duplicate")
    await manager.add_word(chat.tg_chat_id, "duplicate")

    words = await manager.get_chat_words(chat.tg_chat_id)
    assert words.count("duplicate") == 1


@pytest.mark.asyncio
async def test_remove_nonexistent_word(manager):
    await manager.cache.initialize()

    chat = await Chat.create(tg_chat_id=1006, chat_type="group")

    await manager.remove_word(chat.tg_chat_id, "nonexistent")

    words = await manager.get_chat_words(chat.tg_chat_id)
    assert "nonexistent" not in words


@pytest.mark.asyncio
async def test_multiple_chats(manager):
    await manager.cache.initialize()

    chat1 = await Chat.create(tg_chat_id=2001, chat_type="group")
    chat2 = await Chat.create(tg_chat_id=2002, chat_type="group")

    await manager.add_word(chat1.tg_chat_id, "chat1word")
    await manager.add_word(chat2.tg_chat_id, "chat2word")

    words1 = await manager.get_chat_words(chat1.tg_chat_id)
    words2 = await manager.get_chat_words(chat2.tg_chat_id)

    assert "chat1word" in words1
    assert "chat1word" not in words2
    assert "chat2word" in words2
    assert "chat2word" not in words1
