import os
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from aiogram.types import Update


class _StubClient:
    def __init__(self, *args, **kwargs):
        pass

    async def start(self):
        return None

    async def stop(self):
        return None


pyrogram_module = types.ModuleType("pyrogram")
pyrogram_client_module = types.ModuleType("pyrogram.client")
pyrogram_client_module.Client = _StubClient
pyrogram_module.client = pyrogram_client_module
sys.modules.setdefault("pyrogram", pyrogram_module)
sys.modules.setdefault("pyrogram.client", pyrogram_client_module)

os.environ.setdefault("LOGS__CHAT_ID", "1")
os.environ.setdefault("LOGS__CHAT_ACTIVATE_THREAD_ID", "1")
os.environ.setdefault("LOGS__ACCESS_LEVELS_THREAD_ID", "1")
os.environ.setdefault("LOGS__PUNISHMENTS_THREAD_ID", "1")
os.environ.setdefault("LOGS__INVITES_THREAD_ID", "1")
os.environ.setdefault("LOGS__GENERAL_THREAD_ID", "1")
os.environ.setdefault("TOKEN", "test-token")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "test-hash")
os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")
os.environ.setdefault("OWNER_TELEGRAM_IDS", "[1]")
os.environ.setdefault("ADMIN_TELEGRAM_IDS", "[1]")
os.environ.setdefault("SILENT_TELEGRAM_IDS", "[]")
os.environ.setdefault("MASSFORM_CHAT_ID", "1")

import src.bot.middlewares.message_logger as message_logger_module

from src.bot.middlewares.message_logger import MessageLoggerMiddleware

pytestmark = pytest.mark.asyncio


def make_photo_message_update(
    chat_id: int, message_id: int, thread_id: int, media_group_id: str
) -> Update:
    return Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": message_id,
                "date": 1_717_000_000,
                "chat": {
                    "id": chat_id,
                    "type": "supergroup",
                    "title": "Reaction monitor",
                },
                "message_thread_id": thread_id,
                "from": {
                    "id": 555,
                    "is_bot": False,
                    "first_name": "Tester",
                },
                "photo": [
                    {
                        "file_id": "photo-file-id",
                        "file_unique_id": "photo-unique-id",
                        "width": 100,
                        "height": 100,
                    }
                ],
                "media_group_id": media_group_id,
            },
        }
    )


def make_reaction_update(chat_id: int, message_id: int) -> Update:
    return Update.model_validate(
        {
            "update_id": 2,
            "message_reaction": {
                "chat": {
                    "id": chat_id,
                    "type": "supergroup",
                    "title": "Reaction monitor",
                },
                "message_id": message_id,
                "date": 1_717_000_100,
                "old_reaction": [],
                "new_reaction": [{"type": "emoji", "emoji": "👍"}],
                "user": {
                    "id": 555,
                    "is_bot": False,
                    "first_name": "Tester",
                },
            },
        }
    )


async def test_photo_message_logs_media_group_and_creates_watch(monkeypatch):
    chat_id = -100123
    thread_id = 77
    message_id = 101
    media_group_id = "album-1"

    monkeypatch.setattr(
        message_logger_module.settings,
        "REACTION_MONITOR_CHAT_ID",
        chat_id,
        raising=False,
    )
    monkeypatch.setattr(
        message_logger_module.settings,
        "REACTION_MONITOR_TOPIC_ID",
        thread_id,
        raising=False,
    )

    add_message = AsyncMock()
    add_watch = AsyncMock()
    chat_activation = AsyncMock()
    increment_messages_count = AsyncMock()

    monkeypatch.setattr(
        message_logger_module.managers.message_logs, "add_message", add_message
    )
    monkeypatch.setattr(
        message_logger_module.managers.reaction_watches, "add_watch", add_watch
    )
    monkeypatch.setattr(
        message_logger_module.managers.user_roles,
        "chat_activation",
        chat_activation,
    )
    monkeypatch.setattr(
        message_logger_module.managers.users,
        "increment_messages_count",
        increment_messages_count,
    )

    middleware = MessageLoggerMiddleware()
    handler = AsyncMock(return_value=None)

    await middleware(
        handler,
        make_photo_message_update(chat_id, message_id, thread_id, media_group_id),
        {},
    )

    add_message.assert_awaited_once_with(
        chat_id, message_id, thread_id, media_group_id
    )
    add_watch.assert_awaited_once_with(chat_id, message_id, thread_id)
    chat_activation.assert_awaited_once_with(555, chat_id)
    increment_messages_count.assert_awaited_once_with(555)


async def test_reaction_resolves_entire_photo_media_group(monkeypatch):
    chat_id = -100123
    message_id = 101

    monkeypatch.setattr(
        message_logger_module.settings,
        "REACTION_MONITOR_CHAT_ID",
        chat_id,
        raising=False,
    )

    get_message_log = AsyncMock(
        return_value=SimpleNamespace(media_group_id="album-1", message_thread_id=77)
    )
    get_media_group_messages = AsyncMock(return_value=[101, 102])
    mark_resolved = AsyncMock()

    monkeypatch.setattr(
        message_logger_module.managers.message_logs,
        "get_message_log",
        get_message_log,
    )
    monkeypatch.setattr(
        message_logger_module.managers.message_logs,
        "get_media_group_messages",
        get_media_group_messages,
    )
    monkeypatch.setattr(
        message_logger_module.managers.reaction_watches,
        "mark_resolved",
        mark_resolved,
    )

    middleware = MessageLoggerMiddleware()
    handler = AsyncMock(return_value=None)

    await middleware(handler, make_reaction_update(chat_id, message_id), {})

    get_message_log.assert_awaited_once_with(chat_id, message_id)
    get_media_group_messages.assert_awaited_once_with(chat_id, "album-1", 77)
    assert mark_resolved.await_args_list == [call(chat_id, 101), call(chat_id, 102)]
    handler.assert_not_awaited()
