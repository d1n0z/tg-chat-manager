import pytest
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from tortoise import Tortoise

from src.core.managers.invite_usage import InviteUsageManager
from src.core.models import InviteUsage, InviteLink, User, Chat


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
async def chat():
    return await Chat.create(tg_chat_id=1000, title="InviteUsageTestChat")


@pytest_asyncio.fixture
async def user():
    return await User.create(tg_user_id=777, username="InviteUsageUser")


@pytest_asyncio.fixture
async def invite(chat, user):
    return await InviteLink.create(
        token="INVITE_USAGE_TEST",
        chat=chat,
        creator=user,
        max_uses=10,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        is_active=True,
    )


@pytest_asyncio.fixture
async def manager(init_db):
    m = InviteUsageManager()
    await m.cache.initialize()
    yield m
    await m.cache.sync()


@pytest.mark.asyncio
async def test_add_usage(manager, invite, user):
    used_at = datetime.now(timezone.utc)
    created = await manager.add_usage(invite.token, user.tg_user_id, used_at=used_at)
    assert created is True

    cached = await manager.get((invite.token, user.tg_user_id))
    assert cached is not None
    assert cached.invite_token == invite.token
    assert cached.tg_user_id == user.tg_user_id
    assert abs((cached.used_at - used_at).total_seconds()) < 1


@pytest.mark.asyncio
async def test_add_duplicate_usage(manager, invite, user):
    used_at = datetime.now(timezone.utc)
    created1 = await manager.add_usage(invite.token, user.tg_user_id, used_at)
    created2 = await manager.add_usage(invite.token, user.tg_user_id, used_at)
    assert created1 is True
    assert created2 is False


@pytest.mark.asyncio
async def test_remove_usage(manager, invite, user):
    await manager.add_usage(invite.token, user.tg_user_id)
    await manager.remove_usage(invite.token, user.tg_user_id)
    cached = await manager.get((invite.token, user.tg_user_id))
    assert cached is None
    assert not await InviteUsage.filter(invite_id=invite.id, user_id=user.id).exists()


@pytest.mark.asyncio
async def test_get_invite_usages(manager, invite, user):
    u2 = await User.create(tg_user_id=888, username="AnotherUser")
    await manager.add_usage(invite.token, user.tg_user_id)
    await manager.add_usage(invite.token, u2.tg_user_id)

    usages = await manager.get_invite_usages(invite.token)
    assert len(usages) == 2
    user_ids = {u.tg_user_id for u in usages}
    assert user.tg_user_id in user_ids
    assert u2.tg_user_id in user_ids


@pytest.mark.asyncio
async def test_get_user_usages(manager, invite, user):
    chat2 = await Chat.create(tg_chat_id=2000, title="AnotherChat")
    invite2 = await InviteLink.create(
        token="INVITE_USAGE_TEST_2",
        chat=chat2,
        creator=user,
        max_uses=5,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        is_active=True,
    )

    await manager.add_usage(invite.token, user.tg_user_id)
    await manager.add_usage(invite2.token, user.tg_user_id)

    usages = await manager.get_user_usages(user.tg_user_id)
    assert len(usages) == 2
    invite_tokens = {u.invite_token for u in usages}
    assert invite.token in invite_tokens
    assert invite2.token in invite_tokens


@pytest.mark.asyncio
async def test_sync_creates_and_updates(manager, invite, user):
    used_at_1 = datetime.now(timezone.utc) - timedelta(minutes=5)
    await manager.add_usage(invite.token, user.tg_user_id, used_at_1)
    await manager.cache.sync()
    
    db_usage = await InviteUsage.filter(invite_id=invite.id, user_id=user.id).first()
    assert db_usage is not None
