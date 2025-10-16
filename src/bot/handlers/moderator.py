from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject

from src.bot.filters import RoleFilter
from src.bot.types import Message
from src.core import enums

router = Router()


@router.message(
    Command("clear"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def clear_messages(message: Message, command: CommandObject):
    if message.reply_to_message:
        await message.reply_to_message.delete()
        await message.delete()
        return

    if not command.args:
        await message.answer(
            "Использование: /clear [количество(1-100)] или ответом на сообщение"
        )
        return

    try:
        count = int(command.args)
        if count < 1 or count > 100:
            await message.answer("Количество должно быть от 1 до 100")
            return

        message_ids = [message.message_id - i for i in range(count + 1)]
        await message.bot.delete_messages(message.chat.id, message_ids)
    except Exception:
        await message.answer("Ошибка при удалении сообщений")
