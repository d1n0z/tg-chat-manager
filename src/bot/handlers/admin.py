import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from aiogram.filters import CommandObject

from src.bot.filters import Command, RoleFilter
from src.bot.types import Message
from src.bot.utils import get_user_display
from src.core import enums, managers

router = Router()


@router.message(
    Command("words"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def words_command(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("Использование: /words [add|remove|list].")

    args = command.args.split(maxsplit=1)
    action = args[0].lower()

    if action == "add":
        if len(args) < 2:
            return await message.answer(
                "Укажите слово для добавления: /words add [слово]."
            )
        word = args[1].strip().lower()
        await managers.word_filters.add_word(
            message.chat.id, word, message.from_user.id
        )
        return await message.answer(f"Слово '<code>{word}</code>' добавлено в фильтр.")

    elif action == "remove":
        if len(args) < 2:
            return await message.answer("Укажите слово для удаления.")
        word = args[1].strip().lower()
        await managers.word_filters.remove_word(message.chat.id, word)
        return await message.answer(f"Слово '<code>{word}</code>' удалено из фильтра.")

    elif action == "list":
        words = await managers.word_filters.get_chat_words(message.chat.id)
        if not words:
            return await message.answer("Фильтр слов пуст.")
        text = f"Фильтр слов ({len(words)}):\n\n"
        for i, word in enumerate(sorted(words), 1):
            text += f"{i}. <code>{word}</code>\n"
        return await message.answer(text)

    else:
        return await message.answer(
            "Неизвестное действие. Используйте: add, remove, list."
        )


@router.message(
    Command("cluster"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def cluster_command(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("Использование: /cluster [add|remove|list].")

    action = command.args.lower()
    if action == "add":
        global_cluster = await managers.clusters.repo.get_global()
        await managers.chats.edit(message.chat.id, cluster_id=global_cluster.id)
        await managers.clusters.add_chat(global_cluster.id, message.chat.id)
        return await message.answer("Чат добавлен в глобальный кластер.")

    elif action == "remove":
        cluster_id = await managers.chats.get(message.chat.id, "cluster_id")
        if cluster_id:
            await managers.clusters.remove_chat(cluster_id, message.chat.id)
        await managers.chats.edit(message.chat.id, cluster_id=None)
        return await message.answer("Чат удалён из кластера.")

    elif action == "list":
        global_cluster = await managers.clusters.repo.get_global()
        tg_chat_ids = await managers.clusters.get_chats(global_cluster.id)
        if not tg_chat_ids:
            return await message.answer("В глобальном кластере нет чатов.")

        text = "Чаты в глобальном кластере:\n\n"
        for tg_chat_id in tg_chat_ids:
            title = await managers.chats.get(tg_chat_id, "title")
            text += f"• {title or 'Unknown'} (ID: <code>{tg_chat_id}</code>)\n"
        return await message.answer(text)

    else:
        return await message.answer(
            "Неизвестное действие. Используйте: add, remove, list."
        )


@router.message(
    Command("setwelcome"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def setwelcome_command(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("Использование: /setwelcome [сообщение].")
    global_cluster = await managers.clusters.repo.get_global()
    await managers.welcome_messages.set_message(
        global_cluster.id, command.args, message.from_user.id
    )
    return await message.answer(
        f"{await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True)} успешно установил новое приветственное сообщение:\n{command.args}"
    )


@router.message(
    Command("resetwelcome"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def resetwelcome_command(message: Message, command: CommandObject):
    global_cluster = await managers.clusters.repo.get_global()
    if not await managers.welcome_messages.get(global_cluster.id):
        return await message.answer("Приветственное сообщение не установлено.")
    await managers.welcome_messages.remove_message(global_cluster.id)
    return await message.answer(
        f"{await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True)} успешно удалил приветственное сообщение."
    )


@router.message(
    Command("getwelcome"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def getwelcome_command(message: Message, command: CommandObject):
    global_cluster = await managers.clusters.repo.get_global()
    welcome = await managers.welcome_messages.get(global_cluster.id)
    if not welcome:
        return await message.answer(
            "Приветственное сообщение не установлено, используйте команду /setwelcome [сообщение]."
        )
    return await message.answer(f"Текущее приветственное сообщение:\n{welcome.text}")


_news_cooldown = datetime.now(timezone.utc) - timedelta(minutes=10)


@router.message(
    Command("news"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def news_command(message: Message, command: CommandObject):
    global _news_cooldown

    async def send_message(chat_id: int, bot: Bot, text: str):
        try:
            await bot.send_message(chat_id, text=text)
        except TelegramForbiddenError:
            pass
        except TelegramNotFound:
            pass
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            return await send_message(chat_id, bot, text)
        except TelegramAPIError:
            pass
        except Exception:
            pass
        else:
            return True
        return False

    if not command.args:
        return await message.answer("Использование: /news [текст].")

    if (rest := (datetime.now(timezone.utc) - _news_cooldown)) < timedelta(minutes=10):
        return await message.answer(
            f"Подождите {int(rest.total_seconds() // 60)} минут перед отправкой следующей команды /news."
        )

    count = 0
    global_cluster = await managers.clusters.repo.get_global()
    for user_id in await managers.clusters.get_chats(global_cluster.id):
        count += await send_message(user_id, message.bot, command.args)
    return await message.answer(f"Рассылка завершена. Отправлено в {count} чатов.")
