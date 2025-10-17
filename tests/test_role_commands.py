import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import Message, User, Chat
from aiogram.enums import ChatType
from aiogram.filters import CommandObject
from src.core import enums
from src.bot.handlers import senior_moderator


@pytest.fixture
def mock_managers():
    with patch("src.bot.handlers.senior_moderator.managers") as mock:
        mock.users.is_owner = AsyncMock(return_value=False)
        mock.user_roles.get = AsyncMock(return_value=None)
        mock.user_roles.add_role = AsyncMock()
        mock.user_roles.remove_role = AsyncMock()
        mock.user_roles.make_cache_key = MagicMock(side_effect=lambda uid, cid: f"{uid}_{cid}")
        mock.pyrogram_client.is_connected = False
        mock.pyrogram_client.start = AsyncMock()
        mock.pyrogram_client.get_users = AsyncMock()
        yield mock


@pytest.fixture
def mock_get_user_display():
    with patch("src.bot.handlers.senior_moderator.get_user_display") as mock:
        mock.return_value = "TestUser"
        yield mock


def create_message(user_id=1, chat_id=-100, reply_user_id=None, args=None):
    msg = MagicMock(spec=Message)
    msg.from_user = User(id=user_id, is_bot=False, first_name="Author")
    msg.chat = Chat(id=chat_id, type=ChatType.SUPERGROUP)
    msg.bot = MagicMock()
    msg.bot.id = 999
    msg.answer = AsyncMock()
    
    if reply_user_id:
        msg.reply_to_message = MagicMock()
        msg.reply_to_message.from_user = User(id=reply_user_id, is_bot=False, first_name="Target")
    else:
        msg.reply_to_message = None
    
    return msg


class TestSetRole:
    @pytest.mark.asyncio
    async def test_setrole_no_args_no_reply(self, mock_managers, mock_get_user_display):
        msg = create_message()
        cmd = CommandObject(command="setrole", args=None)
        
        await senior_moderator.set_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "Использование:" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_setrole_reply_no_args(self, mock_managers, mock_get_user_display):
        msg = create_message(reply_user_id=2)
        cmd = CommandObject(command="setrole", args=None)
        
        await senior_moderator.set_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "Использование:" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_setrole_invalid_role(self, mock_managers, mock_get_user_display):
        msg = create_message(reply_user_id=2)
        cmd = CommandObject(command="setrole", args="invalid_role")
        
        await senior_moderator.set_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "Неверная роль" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_setrole_admin_not_owner(self, mock_managers, mock_get_user_display):
        mock_managers.users.is_owner.return_value = False
        mock_managers.user_roles.get.return_value = enums.Role.senior_moderator
        
        msg = create_message(reply_user_id=2)
        cmd = CommandObject(command="setrole", args="admin")
        
        await senior_moderator.set_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "Только владелец" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_setrole_senior_moderator_not_admin(self, mock_managers, mock_get_user_display):
        mock_managers.users.is_owner.return_value = False
        mock_managers.user_roles.get.return_value = enums.Role.senior_moderator
        
        msg = create_message(reply_user_id=2)
        cmd = CommandObject(command="setrole", args="senior_moderator")
        
        await senior_moderator.set_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "Только администратор" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_setrole_to_self(self, mock_managers, mock_get_user_display):
        msg = create_message(user_id=1, reply_user_id=1)
        cmd = CommandObject(command="setrole", args="moderator")
        
        await senior_moderator.set_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "самому себе" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_setrole_to_bot(self, mock_managers, mock_get_user_display):
        msg = create_message(reply_user_id=999)
        cmd = CommandObject(command="setrole", args="moderator")
        
        await senior_moderator.set_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "роль бота" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_setrole_target_higher_role(self, mock_managers, mock_get_user_display):
        mock_managers.users.is_owner.return_value = False
        
        async def get_role(key, field):
            if "1_" in key:
                return enums.Role.senior_moderator
            if "2_" in key:
                return enums.Role.admin
            return None
        
        mock_managers.user_roles.get.side_effect = get_role
        
        msg = create_message(user_id=1, reply_user_id=2)
        cmd = CommandObject(command="setrole", args="moderator")
        
        await senior_moderator.set_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "равной или выше" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_setrole_success_reply(self, mock_managers, mock_get_user_display):
        async def get_role(key, field):
            if "1_" in key:
                return enums.Role.senior_moderator
            return None
        
        mock_managers.user_roles.get.side_effect = get_role
        
        msg = create_message(reply_user_id=2)
        cmd = CommandObject(command="setrole", args="moderator")
        
        await senior_moderator.set_role(msg, cmd)
        
        mock_managers.user_roles.add_role.assert_called_once_with(2, -100, enums.Role.moderator, 1)
        msg.answer.assert_called_once()
        assert "установлена" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_setrole_owner_can_set_admin(self, mock_managers, mock_get_user_display):
        mock_managers.users.is_owner.return_value = True
        mock_managers.user_roles.get.return_value = enums.Role.admin
        
        msg = create_message(reply_user_id=2)
        cmd = CommandObject(command="setrole", args="admin")
        
        await senior_moderator.set_role(msg, cmd)
        
        mock_managers.user_roles.add_role.assert_called_once_with(2, -100, enums.Role.admin, 1)

    @pytest.mark.asyncio
    async def test_setrole_admin_can_set_senior_moderator(self, mock_managers, mock_get_user_display):
        async def get_role(key, field):
            if "1_" in key:
                return enums.Role.admin
            return None
        
        mock_managers.user_roles.get.side_effect = get_role
        
        msg = create_message(reply_user_id=2)
        cmd = CommandObject(command="setrole", args="senior_moderator")
        
        await senior_moderator.set_role(msg, cmd)
        
        mock_managers.user_roles.add_role.assert_called_once_with(2, -100, enums.Role.senior_moderator, 1)

    @pytest.mark.asyncio
    async def test_setrole_senior_moderator_cannot_set_high_roles(self, mock_managers, mock_get_user_display):
        mock_managers.users.is_owner.return_value = False
        
        async def get_role(key, field):
            if "1_" in key:
                return enums.Role.senior_moderator
            return None
        
        mock_managers.user_roles.get.side_effect = get_role
        
        msg = create_message(reply_user_id=2)
        cmd = CommandObject(command="setrole", args="admin")
        
        await senior_moderator.set_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "Только владелец" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_setrole_target_equal_role(self, mock_managers, mock_get_user_display):
        mock_managers.users.is_owner.return_value = False
        
        async def get_role(key, field):
            return enums.Role.senior_moderator
        
        mock_managers.user_roles.get.side_effect = get_role
        
        msg = create_message(user_id=1, reply_user_id=2)
        cmd = CommandObject(command="setrole", args="moderator")
        
        await senior_moderator.set_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "равной или выше" in msg.answer.call_args[0][0]


class TestRemoveRole:
    @pytest.mark.asyncio
    async def test_removerole_no_args_no_reply(self, mock_managers, mock_get_user_display):
        msg = create_message()
        cmd = CommandObject(command="removerole", args=None)
        
        await senior_moderator.remove_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "Использование:" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_removerole_from_self(self, mock_managers, mock_get_user_display):
        msg = create_message(user_id=1, reply_user_id=1)
        cmd = CommandObject(command="removerole", args=None)
        
        await senior_moderator.remove_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "самому себе" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_removerole_from_bot(self, mock_managers, mock_get_user_display):
        msg = create_message(reply_user_id=999)
        cmd = CommandObject(command="removerole", args=None)
        
        await senior_moderator.remove_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "роль бота" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_removerole_target_higher_role(self, mock_managers, mock_get_user_display):
        mock_managers.users.is_owner.return_value = False
        
        async def get_role(key, field):
            if "1_" in key:
                return enums.Role.senior_moderator
            if "2_" in key:
                return enums.Role.admin
            return None
        
        mock_managers.user_roles.get.side_effect = get_role
        
        msg = create_message(user_id=1, reply_user_id=2)
        cmd = CommandObject(command="removerole", args=None)
        
        await senior_moderator.remove_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "равной или выше" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_removerole_success_reply(self, mock_managers, mock_get_user_display):
        async def get_role(key, field):
            if "1_" in key:
                return enums.Role.senior_moderator
            return None
        
        mock_managers.user_roles.get.side_effect = get_role
        
        msg = create_message(reply_user_id=2)
        cmd = CommandObject(command="removerole", args=None)
        
        await senior_moderator.remove_role(msg, cmd)
        
        mock_managers.user_roles.remove_role.assert_called_once_with(2, -100)
        msg.answer.assert_called_once()
        assert "удалена" in msg.answer.call_args[0][0]

    @pytest.mark.asyncio
    async def test_removerole_owner_can_remove_any(self, mock_managers, mock_get_user_display):
        mock_managers.users.is_owner.return_value = True
        
        async def get_role(key, field):
            if "1_" in key:
                return enums.Role.senior_moderator
            if "2_" in key:
                return enums.Role.admin
            return None
        
        mock_managers.user_roles.get.side_effect = get_role
        
        msg = create_message(user_id=1, reply_user_id=2)
        cmd = CommandObject(command="removerole", args=None)
        
        await senior_moderator.remove_role(msg, cmd)
        
        mock_managers.user_roles.remove_role.assert_called_once_with(2, -100)

    @pytest.mark.asyncio
    async def test_removerole_target_equal_role(self, mock_managers, mock_get_user_display):
        mock_managers.users.is_owner.return_value = False
        
        async def get_role(key, field):
            return enums.Role.senior_moderator
        
        mock_managers.user_roles.get.side_effect = get_role
        
        msg = create_message(user_id=1, reply_user_id=2)
        cmd = CommandObject(command="removerole", args=None)
        
        await senior_moderator.remove_role(msg, cmd)
        
        msg.answer.assert_called_once()
        assert "равной или выше" in msg.answer.call_args[0][0]
