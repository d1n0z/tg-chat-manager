import loguru
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from pyrogram.errors import UsernameNotOccupied

from src.bot.types import Message
from src.core import managers

router = Router()


@router.message(Command("id"), F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}))
async def get_user_id(message: Message, command: CommandObject):
    if message.entities and len(message.entities) > 1:
        mention = message.entities[1]
        if mention.type == "text_mention" and mention.user:
            return await message.answer(
                f"ID пользователя {mention.user.first_name}: <code>{mention.user.id}</code>"
            )

    if not command.args:
        if message.from_user and message.from_user.id and message.from_user.username:
            return await message.answer(
                f"ID пользователя @{message.from_user.username}: <code>{message.from_user.id}</code>"
            )

        return await message.answer(
            "Использование: /id @username или упомяните пользователя."
        )

    username = command.args.lstrip("@")

    try:
        if not managers.pyrogram_client.is_connected:
            await managers.pyrogram_client.start()
        user = await managers.pyrogram_client.get_users(username)
        if isinstance(user, list):
            user = user[0]
        return await message.answer(
            f"ID пользователя @{username}: <code>{user.id}</code>"
        )
    except UsernameNotOccupied:
        return await message.answer(f"Пользователь @{username} не найден.")
    except Exception:
        loguru.logger.exception("user.id handler exception:")
        return await message.answer("Ошибка при получении ID.")
