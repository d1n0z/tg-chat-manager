import loguru
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandObject

from src.bot.filters import Command, RoleFilter
from src.bot.types import Message
from src.bot.utils import get_user_id_by_username
from src.core import enums, managers

router = Router()


@router.message(
    Command("kick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def kick_command(message: Message, command: CommandObject):
    if message.reply_to_message and message.reply_to_message.from_user:
        user_id = message.reply_to_message.from_user.id
        username = message.reply_to_message.from_user.username
    elif command.args:
        username = command.args.lstrip("@")
        user_id = await get_user_id_by_username(username)
        if not user_id:
            await message.answer("Пользователь не найден.")
            return
    else:
        await message.answer("Использование: /kick @username")
        return

    try:
        target = await message.bot.get_chat_member(message.chat.id, user_id)
        bot_member = await message.bot.get_chat_member(message.chat.id, message.bot.id)

        if target.status in ("creator", "administrator"):
            await message.answer("Невозможно кикнуть администратора.")
            return

        if (
            bot_member.status not in ("creator", "administrator")
            or not hasattr(bot_member, "can_restrict_members")
            or not bot_member.can_restrict_members  # type: ignore
        ):
            await message.answer("У бота нет прав на кик пользователей.")
            return

        initiator_role = (
            await managers.user_roles.get(
                managers.user_roles.make_cache_key(
                    message.from_user.id, message.chat.id
                ),
                "level",
            )
            or enums.Role.user
        )
        target_role = (
            await managers.user_roles.get(
                managers.user_roles.make_cache_key(user_id, message.chat.id), "level"
            )
            or enums.Role.user
        )

        if target_role >= initiator_role:
            await message.answer(
                "Вы не можете кикнуть пользователя с равной или выше ролью."
            )
            return

        await message.bot.ban_chat_member(message.chat.id, user_id)
        await message.bot.unban_chat_member(message.chat.id, user_id)
        await message.answer(f"Пользователь @{username} кикнут из чата.")
    except Exception:
        loguru.logger.exception("admin.kick handler exception:")
        await message.answer("Неизвестная ошибка.")


@router.message(
    Command("gkick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def gkick_command(message: Message, command: CommandObject):
    cluster_id = await managers.chats.get(message.chat.id, "cluster_id")
    if not cluster_id:
        await message.answer("Чат не в кластере.")
        return

    if message.reply_to_message and message.reply_to_message.from_user:
        user_id = message.reply_to_message.from_user.id
        username = message.reply_to_message.from_user.username
    elif command.args:
        username = command.args.lstrip("@")
        user_id = await get_user_id_by_username(username)
        if not user_id:
            await message.answer("Пользователь не найден.")
            return
    else:
        await message.answer("Использование: /gkick @username")
        return

    try:
        tg_chat_ids = await managers.clusters.get_chats(cluster_id)
        kicked = 0
        for tg_chat_id in tg_chat_ids:
            try:
                initiator_role = (
                    await managers.user_roles.get(
                        managers.user_roles.make_cache_key(
                            message.from_user.id, tg_chat_id
                        ),
                        "level",
                    )
                    or enums.Role.user
                )
                target_role = (
                    await managers.user_roles.get(
                        managers.user_roles.make_cache_key(user_id, tg_chat_id), "level"
                    )
                    or enums.Role.user
                )

                if target_role >= initiator_role:
                    continue

                bot_member = await message.bot.get_chat_member(
                    tg_chat_id, message.bot.id
                )
                if (
                    bot_member.status in ("creator", "administrator")
                    and hasattr(bot_member, "can_restrict_members")
                    and bot_member.can_restrict_members  # type: ignore
                ):
                    await message.bot.ban_chat_member(tg_chat_id, user_id)
                    await message.bot.unban_chat_member(tg_chat_id, user_id)
                    kicked += 1
            except Exception:
                pass

        await message.answer(
            f"Пользователь @{username} кикнут из {kicked} чатов кластера."
        )
    except Exception:
        loguru.logger.exception("admin.gkick handler exception:")
        await message.answer("Неизвестная ошибка.")


@router.message(
    Command("words"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def words_command(message: Message, command: CommandObject):
    if not command.args:
        await message.answer("Использование: /words [add|remove|list].")
        return

    args = command.args.split(maxsplit=1)
    action = args[0].lower()

    if action == "add":
        if len(args) < 2:
            await message.answer("Укажите слово для добавления: /words add [слово].")
            return
        word = args[1].strip().lower()
        await managers.word_filters.add_word(
            message.chat.id, word, message.from_user.id
        )
        await message.answer(f"Слово '<code>{word}</code>' добавлено в фильтр.")

    elif action == "remove":
        if len(args) < 2:
            await message.answer("Укажите слово для удаления.")
            return
        word = args[1].strip().lower()
        await managers.word_filters.remove_word(message.chat.id, word)
        await message.answer(f"Слово '<code>{word}</code>' удалено из фильтра.")

    elif action == "list":
        words = await managers.word_filters.get_chat_words(message.chat.id)
        if not words:
            await message.answer("Фильтр слов пуст.")
            return
        text = f"Фильтр слов ({len(words)}):\n\n"
        for i, word in enumerate(sorted(words), 1):
            text += f"{i}. <code>{word}</code>\n"
        await message.answer(text)

    else:
        await message.answer("Неизвестное действие. Используйте: add, remove, list.")


@router.message(
    Command("cluster"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def cluster_command(message: Message, command: CommandObject):
    if not command.args:
        await message.answer("Использование: /cluster [add|remove|list].")
        return

    action = command.args.lower()
    if action == "add":
        global_cluster = await managers.clusters.repo.get_global()
        await managers.chats.edit(message.chat.id, cluster_id=global_cluster.id)
        await managers.clusters.add_chat(global_cluster.id, message.chat.id)
        await message.answer("Чат добавлен в глобальный кластер.")

    elif action == "remove":
        cluster_id = await managers.chats.get(message.chat.id, "cluster_id")
        if cluster_id:
            await managers.clusters.remove_chat(cluster_id, message.chat.id)
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
