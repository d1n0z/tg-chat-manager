from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject

from src.bot.filters import RoleFilter
from src.bot.types import Message
from src.core import enums, managers

router = Router()


@router.message(
    Command("cluster"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def cluster_command(message: Message, command: CommandObject):
    if not command.args:
        await message.answer("Использование: /cluster <add|remove|list>.")
        return

    action = command.args.lower()
    if action == "add":
        global_cluster = await managers.clusters.repo.get_global()
        await managers.chats.edit(message.chat.id, cluster_id=global_cluster.id)
        await message.answer("Чат добавлен в глобальный кластер.")

    elif action == "remove":
        await managers.chats.edit(message.chat.id, cluster_id=None)
        await message.answer("Чат удалён из кластера.")

    elif action == "list":
        global_cluster = await managers.clusters.repo.get_global()
        tg_chat_ids = await managers.clusters.get_chats(global_cluster.id)
        if not tg_chat_ids:
            await message.answer("В глобальном кластере нет чатов.")
            return

        text = "Чаты в глобальном кластере:\n\n"
        for tg_chat_id in tg_chat_ids:
            title = await managers.chats.get(tg_chat_id, "title")
            text += f"• {title or 'Unknown'} (ID: <code>{tg_chat_id}</code>)\n"
        await message.answer(text)

    else:
        await message.answer("Неизвестное действие. Используйте: add, remove, list.")
