import asyncio
from datetime import datetime, timedelta, timezone

import loguru
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
from src.bot.keyboards import keyboards
from src.bot.types import Message
from src.bot.utils import get_user_display, get_user_id_by_username, parse_duration
from src.core import enums, managers
from src.core.config import settings

router = Router()


@router.message(
    Command("gkick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def gkick_command(message: Message, command: CommandObject):
    cluster_id = await managers.chats.get(message.chat.id, "cluster_id")
    if not cluster_id:
        return await message.answer("Чат не в кластере.")

    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and not message.reply_to_message.is_topic_message
    ):
        user_id = message.reply_to_message.from_user.id
        username = message.reply_to_message.from_user.username
        reason = command.args or None
    elif command.args:
        args = command.args.split(maxsplit=1)
        username = args[0].lstrip("@")
        reason = args[1] if len(args) > 1 else None
        user_id = await get_user_id_by_username(username)
        if not user_id:
            return await message.answer("Пользователь не найден.")
    else:
        return await message.answer("Использование: /gkick @username")

    try:
        tg_chat_ids = await managers.clusters.get_chats(cluster_id)
        kicked = []
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

                member = await message.bot.get_chat_member(tg_chat_id, user_id)
                bot_member = await message.bot.get_chat_member(tg_chat_id, message.bot.id)
                if (
                    bot_member.status in ("creator", "administrator")
                    and hasattr(bot_member, "can_restrict_members")
                    and bot_member.can_restrict_members  # type: ignore
                    and member.status == "member"
                ):
                    await message.bot.ban_chat_member(tg_chat_id, user_id)
                    await message.bot.unban_chat_member(tg_chat_id, user_id)
                    kicked.append(tg_chat_id)
            except Exception:
                pass

        kicked = [(await message.bot.get_chat(tg_chat_id)).title for tg_chat_id in kicked]
        kicked = '\n'.join([f"{k}. {i}" for k, i in enumerate(kicked[:25], start=1) if i])
        if kicked:
            invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
            await message.bot.send_message(
                chat_id=settings.logs.chat_id,
                text=f"""#gkick
    ➡️ Из чата: {message.chat.title}\n
    ➡️ Пользователь: {(setter := await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True))}
    ➡️ Уровень прав: {initiator_role.value}
    ℹ️ Действие: Исключил из чата
    ℹ️ Причина: {reason or "Не указана"}
    ➡️ Цель: @{username}""",
                message_thread_id=settings.logs.punishments_thread_id,
                reply_markup=keyboards.join(0, invite) if invite else None,
            )

            return await message.answer(
                f"{setter} исключил глобально пользователя @{username}{f' по причине "{reason}"' if reason else ''}\n\nИсключен из чатов:\n{kicked}"
            )
        return await message.answer(
            f"{'Не удалось исключить глобально пользователя' if username else 'Пользователь не найден: '} @{username}."
        )
    except Exception:
        loguru.logger.exception("admin.gkick handler exception:")
        return await message.answer("Неизвестная ошибка.")


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


@router.message(
    Command("gban"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def gban_command(message: Message, command: CommandObject):
    cluster_id = await managers.chats.get(message.chat.id, "cluster_id")
    if not cluster_id:
        return await message.answer("Чат не в кластере.")

    try:
        if (
            message.reply_to_message
            and message.reply_to_message.from_user
            and not message.reply_to_message.is_topic_message
        ):
            target_user_id = message.reply_to_message.from_user.id
            args = command.args.split(maxsplit=1) if command.args else []
            duration = parse_duration(args[0]) if args else timedelta(days=3650)
            reason = args[1] if len(args) > 1 else None
        else:
            try:
                if not command.args:
                    raise ValueError
                args = command.args.split(maxsplit=2)
                username = args[0].lstrip("@")
                if len(args) > 1 and (duration := parse_duration(args[1])):
                    reason = args[2] if len(args) > 2 else None
                else:
                    duration = timedelta(days=3650)
                    reason = args[1] if len(args) > 1 else None
            except Exception:
                return await message.answer(
                    "Использование: /gban @username [время] [причина] или ответом на сообщение."
                )

            target_user_id = await get_user_id_by_username(username)
            if not target_user_id:
                return await message.answer(f"Пользователь @{username} не найден.")

        if not duration:
            return await message.answer(
                "Неверный формат времени. Используйте: 10m, 1h, 1d."
            )

        if target_user_id == message.from_user.id:
            return await message.answer("Нельзя забанить самого себя.")

        if target_user_id == message.bot.id:
            return await message.answer("Нельзя забанить бота.")

        tg_chat_ids = await managers.clusters.get_chats(cluster_id)
        banned = []
        start_at = datetime.now(timezone.utc)
        end_at = start_at + duration

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
                        managers.user_roles.make_cache_key(target_user_id, tg_chat_id),
                        "level",
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
                    await managers.users.edit(target_user_id, banned_until=end_at)
                    banned.append(tg_chat_id)
            except Exception:
                pass

        try:
            global_cluster = await managers.clusters.repo.get_global()
            await managers.global_bans.add_ban(
                target_user_id,
                global_cluster.id,
                start_at=start_at,
                end_at=end_at,
                reason=reason,
                created_by_tg_id=message.from_user.id,
                active=True,
                auto_unban=True,
            )
        except Exception:
            pass

        username = await get_user_display(target_user_id, message.bot, message.chat.id)
        msk_tz = timezone(timedelta(hours=3))
        end_at_msk = end_at.astimezone(msk_tz)
        end_at_text = (
            f"до {end_at_msk.strftime('%d.%m.%Y %H:%M')}"
            if end_at - datetime.now(timezone.utc) < timedelta(days=3650)
            else "навсегда"
        )
        setter_name = await get_user_display(
            message.from_user.id, message.bot, message.chat.id
        )
        invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
        await message.bot.send_message(
            settings.logs.chat_id,
            f"""#gban
➡️ Из чата: {message.chat.title}\n
➡️ Пользователь: {setter_name}
➡️ Уровень прав: {initiator_role.value}
ℹ️ Действие: Забанил пользователя
ℹ️ Срок: {end_at_text}
ℹ️ Причина: {reason or "Не указана"}
➡️ Цель: {username}""",
            message_thread_id=settings.logs.punishments_thread_id,
            reply_markup=keyboards.join(0, invite) if invite else None,
        )
        
        banned = [(await message.bot.get_chat(tg_chat_id)).title for tg_chat_id in banned]
        banned = '\n'.join([f"{k}. {i}" for k, i in enumerate(banned[:25], start=1) if i])
        return await message.answer(
            f"{setter_name} заблокировал глобально пользователя @{username} {end_at_text}{f' по причине "{reason}"' if reason else ''}\n\nЗаблокирован в чатах:\n{banned}"
        )
    except Exception:
        loguru.logger.exception("admin.gban handler exception:")
        return await message.answer("Неизвестная ошибка.")


@router.message(
    Command("gunban"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.admin),
)
async def gunban_command(message: Message, command: CommandObject):
    cluster_id = await managers.chats.get(message.chat.id, "cluster_id")
    if not cluster_id:
        return await message.answer("Чат не в кластере.")

    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and not message.reply_to_message.is_topic_message
    ):
        target_user_id = message.reply_to_message.from_user.id
    elif command.args:
        username = command.args.lstrip("@")
        target_user_id = await get_user_id_by_username(username)
        if not target_user_id:
            return await message.answer(f"Пользователь @{username} не найден.")
    else:
        return await message.answer(
            "Использование: /gunban @username или ответом на сообщение."
        )

    try:
        tg_chat_ids = await managers.clusters.get_chats(cluster_id)
        unbanned = 0
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
                        managers.user_roles.make_cache_key(target_user_id, tg_chat_id),
                        "level",
                    )
                    or enums.Role.user
                )
                if target_role >= initiator_role:
                    continue
                await message.bot.unban_chat_member(tg_chat_id, target_user_id)
                await managers.users.edit(target_user_id, banned_until=None)
                unbanned += 1
            except Exception:
                pass

        try:
            global_cluster = await managers.clusters.repo.get_global()
            await managers.global_bans.remove_ban(target_user_id, global_cluster.id)
        except Exception:
            pass

        username = await get_user_display(target_user_id, message.bot, message.chat.id)
        setter_name = await get_user_display(
            message.from_user.id, message.bot, message.chat.id
        )
        invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
        await message.bot.send_message(
            settings.logs.chat_id,
            f"""#gunban
➡️ Из чата: {message.chat.title}\n
➡️ Пользователь: {setter_name}
➡️ Уровень прав: {initiator_role.value}
ℹ️ Действие: Разбанил пользователя
➡️ Цель: {username}""",
            message_thread_id=settings.logs.punishments_thread_id,
            reply_markup=keyboards.join(0, invite) if invite else None,
        )
        return await message.answer(
            f"{setter_name} разбанил пользователя {username} в {unbanned} чатах кластера."
        )
    except Exception:
        loguru.logger.exception("admin.gunban handler exception:")
        return await message.answer("Неизвестная ошибка.")


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
