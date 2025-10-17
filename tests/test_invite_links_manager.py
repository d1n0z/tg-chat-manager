from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.invite_links import InviteLinkManager
from src.core.models import Chat, InviteLink, User


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
    m = InviteLinkManager()
    await m.cache.initialize()
    yield m
    await m.cache.sync()


@pytest_asyncio.fixture
async def chat():
    return await Chat.create(tg_chat_id=123456, title="TestChat")


@pytest_asyncio.fixture
async def user():
    return await User.create(tg_user_id=999, username="creator")


@pytest.mark.asyncio
async def test_add_invite(manager, chat, user):
    token = "TEST_TOKEN_1"

    await manager.add_invite(
        token=token,
        tg_chat_id=chat.tg_chat_id,
        creator_tg_id=user.tg_user_id,
        max_uses=3,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        single_use=False,
    )

    cached = await manager.get(token)
    assert cached is not None
    assert cached.token == token
    assert cached.tg_chat_id == chat.tg_chat_id
    assert cached.creator_tg_id == user.tg_user_id
    assert cached.max_uses == 3
    assert cached.used_count == 0
    assert cached.is_active is True


@pytest.mark.asyncio
async def test_remove_invite(manager, chat):
    token = "REMOVE_ME"
    await manager.add_invite(token, chat.tg_chat_id)
    await manager.cache.sync()

    assert await InviteLink.filter(token=token).exists()

    await manager.remove_invite(token)
    assert not await InviteLink.filter(token=token).exists()
    cached = await manager.get(token)
    assert cached is None


@pytest.mark.asyncio
async def test_increment_usage(manager, chat):
    token = "INCREMENT_ME"
    await manager.add_invite(token, chat.tg_chat_id, max_uses=2)
    await manager.increment_usage(token)
    await manager.increment_usage(token)

    cached = await manager.get(token)
    assert cached.used_count == 2
    assert cached.is_active is False

    await manager.cache.sync()
    db_row = await InviteLink.get(token=token)
    assert db_row.used_count == 2
    assert db_row.is_active is False


@pytest.mark.asyncio
async def test_is_valid_expiration(manager, chat):
    token = "EXPIRED_LINK"
    expired_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await manager.add_invite(token, chat.tg_chat_id, expires_at=expired_at)

    valid = await manager.is_valid(token)
    assert valid is False


@pytest.mark.asyncio
async def test_is_valid_active_and_uses(manager, chat):
    token = "VALID_LINK"
    await manager.add_invite(token, chat.tg_chat_id, max_uses=3)

    assert await manager.is_valid(token) is True

    await manager.increment_usage(token)
    await manager.increment_usage(token)
    assert await manager.is_valid(token) is True

    await manager.increment_usage(token)
    assert await manager.is_valid(token) is False


@pytest.mark.asyncio
async def test_get_chat_invites(manager, chat):
    await manager.add_invite("LINK_1", chat.tg_chat_id)
    await manager.add_invite("LINK_2", chat.tg_chat_id)
    invites = await manager.get_chat_invites(chat.tg_chat_id)
    assert len(invites) == 2
    tokens = [i.token for i in invites]
    assert "LINK_1" in tokens
    assert "LINK_2" in tokens


@pytest.mark.asyncio
async def test_sync_creates_and_updates(manager, chat):
    token = "SYNC_TOKEN"
    await manager.add_invite(token, chat.tg_chat_id, max_uses=2)
    await manager.increment_usage(token)
    await manager.cache.sync()

    db_row = await InviteLink.get(token=token)
    assert db_row.used_count == 1

    await manager.increment_usage(token)
    await manager.cache.sync()
    db_row = await InviteLink.get(token=token)
    assert db_row.used_count == 2


@pytest.mark.asyncio
async def test_get_fields(manager, chat):
    token = "FIELD_TEST"
    await manager.add_invite(token, chat.tg_chat_id, max_uses=5)
    max_uses = await manager.get(token, "max_uses")
    assert max_uses == 5
    max_uses, used_count = await manager.get(token, ["max_uses", "used_count"])
    assert max_uses == 5 and used_count == 0


@pytest.mark.asyncio
async def test_is_valid_nonexistent(manager):
    assert await manager.is_valid("NONEXISTENT") is False


@pytest.mark.asyncio
async def test_increment_usage_nonexistent(manager):
    result = await manager.increment_usage("NONEXISTENT")
    assert result is False


@pytest.mark.asyncio
async def test_get_chat_invites_empty(manager, chat):
    invites = await manager.get_chat_invites(99999)
    assert invites == []
