from aiogram import Router

from src.bot.filters import Command, IsOwnerFilter
from src.bot.types import Message
from src.bot.utils import get_user_display
from src.core import enums, managers

router = Router()


@router.message(Command("set_role"), IsOwnerFilter())
async def set_role(message: Message):
    args = message.text.split() if message.text else []
    if len(args) < 3:
        return await message.answer(
            "Использование: /set_role <user_id> <role>.\n\n"
            "Доступные роли: user, moderator, senior_moderator, admin."
        )

    try:
        user_id = int(args[1])
        role_str = args[2].lower()
        chat_id = message.chat.id

        try:
            role = enums.Role(role_str)
        except ValueError:
            return await message.answer(
                "Неверная роль. Доступны: user, moderator, senior_moderator, admin."
            )

        await managers.user_roles.add_role(user_id, chat_id, role, message.from_user.id)
        username = await get_user_display(user_id, message.bot, chat_id)
        return await message.answer(
            f"Роль {role.value} установлена пользователю {username}."
        )
    except ValueError:
        return await message.answer("user_id должен быть числом.")
    except Exception as e:
        return await message.answer(f"Ошибка: {e}")
