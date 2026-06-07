from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.enums import ChatType
from aiogram.filters import CommandObject
from aiogram.types import User

class DummyPyrogramClient:
    def __init__(self, *args, **kwargs):
        self.is_connected = False


pyrogram_module = types.ModuleType("pyrogram")
pyrogram_client_module = types.ModuleType("pyrogram.client")
pyrogram_client_module.Client = DummyPyrogramClient
pyrogram_module.client = pyrogram_client_module
sys.modules.setdefault("pyrogram", pyrogram_module)
sys.modules.setdefault("pyrogram.client", pyrogram_client_module)

os.environ.setdefault("LOGS__CHAT_ID", "1")
os.environ.setdefault("LOGS__CHAT_ACTIVATE_THREAD_ID", "1")
os.environ.setdefault("LOGS__ACCESS_LEVELS_THREAD_ID", "1")
os.environ.setdefault("LOGS__PUNISHMENTS_THREAD_ID", "1")
os.environ.setdefault("LOGS__INVITES_THREAD_ID", "1")
os.environ.setdefault("LOGS__GENERAL_THREAD_ID", "1")
os.environ.setdefault("TOKEN", "test")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "test")
os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")
os.environ.setdefault("OWNER_TELEGRAM_IDS", "[1]")
os.environ.setdefault("ADMIN_TELEGRAM_IDS", "[1]")
os.environ.setdefault("SILENT_TELEGRAM_IDS", "[]")
os.environ.setdefault("MASSFORM_CHAT_ID", "1")

moderator_path = Path(__file__).resolve().parents[1] / "src/bot/handlers/moderator.py"
moderator_spec = importlib.util.spec_from_file_location(
    "test_moderator_module", moderator_path
)
moderator = importlib.util.module_from_spec(moderator_spec)
assert moderator_spec and moderator_spec.loader
moderator_spec.loader.exec_module(moderator)


def create_message(user_id=1, reply_user_id=None):
    message = MagicMock()
    message.from_user = User(id=user_id, is_bot=False, first_name="Moderator")
    message.chat = SimpleNamespace(id=-100, type=ChatType.SUPERGROUP, title="Test chat")
    message.bot = MagicMock()
    message.bot.id = 999
    message.bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="member"))
    message.bot.restrict_chat_member = AsyncMock()
    message.bot.send_message = AsyncMock()
    message.answer = AsyncMock()

    if reply_user_id is None:
        message.reply_to_message = None
    else:
        message.reply_to_message = SimpleNamespace(
            from_user=User(id=reply_user_id, is_bot=False, first_name="Target"),
            is_topic_message=False,
        )

    return message


@pytest.fixture
def mock_managers():
    with patch.object(moderator, "managers") as mock:
        async def get_role(cache_key, field):
            if str(cache_key) == "1_-100":
                return moderator.enums.Role.moderator
            return None

        mock.user_roles.get = AsyncMock(side_effect=get_role)
        mock.user_roles.make_cache_key = MagicMock(
            side_effect=lambda user_id, chat_id: f"{user_id}_{chat_id}"
        )
        mock.mutes.add_mute = AsyncMock()
        mock.chats.get = AsyncMock(return_value=None)
        yield mock


@pytest.fixture
def mock_keyboards():
    with patch.object(moderator.keyboards, "mute_actions", return_value=None):
        yield


@pytest.mark.asyncio
async def test_mute_reply_accepts_numeric_minutes_and_full_reason(
    mock_managers, mock_keyboards
):
    message = create_message(reply_user_id=2)
    command = CommandObject(command="mute", args="30 flood spam")

    with patch.object(
        moderator, "get_user_display", AsyncMock(side_effect=["@target", "@moderator"])
    ):
        await moderator.mute_user(message, command)

    assert mock_managers.mutes.add_mute.await_count == 1
    assert mock_managers.mutes.add_mute.await_args.kwargs["reason"] == "flood spam"

    until_date = message.bot.restrict_chat_member.await_args.kwargs["until_date"]
    delta = until_date - datetime.now(timezone.utc)
    assert timedelta(minutes=29) < delta < timedelta(minutes=31)

    answer_text = message.answer.await_args.args[0]
    assert "по причине 30" not in answer_text
    assert "flood spam" in answer_text


@pytest.mark.asyncio
async def test_mute_direct_reason_without_duration_keeps_full_reason(
    mock_managers, mock_keyboards
):
    message = create_message()
    command = CommandObject(command="mute", args="@target flood spam")

    with patch.object(
        moderator, "get_user_id_by_username", AsyncMock(return_value=2)
    ), patch.object(
        moderator, "get_user_display", AsyncMock(side_effect=["@target", "@moderator"])
    ):
        await moderator.mute_user(message, command)

    assert mock_managers.mutes.add_mute.await_args.kwargs["reason"] == "flood spam"

    until_date = message.bot.restrict_chat_member.await_args.kwargs["until_date"]
    delta = until_date - datetime.now(timezone.utc)
    assert timedelta(days=399) < delta < timedelta(days=401)


@pytest.mark.asyncio
async def test_mute_rejects_invalid_duration_token(mock_managers, mock_keyboards):
    message = create_message()
    command = CommandObject(command="mute", args="@target 30x flood")

    with patch.object(
        moderator, "get_user_id_by_username", AsyncMock(return_value=2)
    ):
        await moderator.mute_user(message, command)

    assert message.answer.await_count == 1
    assert "Неверный формат времени" in message.answer.await_args.args[0]
    message.bot.restrict_chat_member.assert_not_awaited()
    mock_managers.mutes.add_mute.assert_not_awaited()


@pytest.mark.asyncio
async def test_gkick_uses_source_chat_role_for_logging(mock_managers):
    message = create_message()
    message.bot.ban_chat_member = AsyncMock()
    message.bot.unban_chat_member = AsyncMock(return_value=True)
    message.bot.get_chat = AsyncMock(
        side_effect=[
            SimpleNamespace(title="Cluster chat 1"),
            SimpleNamespace(title="Cluster chat 2"),
        ]
    )
    command = CommandObject(command="gkick", args="@target flood")

    mock_managers.chats.get.side_effect = lambda chat_id, field: (
        10 if field == "cluster_id" else None
    )
    mock_managers.clusters.get_chats = AsyncMock(return_value=[200, 201])
    mock_managers.nicks.remove_nick = AsyncMock()
    mock_managers.user_roles.remove_role = AsyncMock()

    with patch.object(
        moderator, "get_user_id_by_username", AsyncMock(return_value=2)
    ), patch.object(
        moderator, "get_user_display", AsyncMock(return_value="@moderator")
    ):
        await moderator.gkick_command(message, command)

    assert any(
        call.args == (1, -100)
        for call in mock_managers.user_roles.make_cache_key.call_args_list
    )
    message.bot.send_message.assert_awaited_once()
    answer_text = message.answer.await_args.args[0]
    assert "Cluster chat 1" in answer_text
    assert "Cluster chat 2" in answer_text
