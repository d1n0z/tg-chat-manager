import asyncio
from datetime import datetime, timedelta, timezone

import loguru
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import CommandObject
from aiolimiter import AsyncLimiter

from src.bot.filters import Command, RoleFilter
from src.bot.keyboards import keyboards
from src.bot.types import Message
from src.bot.utils import get_user_display, get_user_id_by_username, parse_duration
from src.core import enums, managers
from src.core.config import settings

router = Router()


@router.message(
    Command("setwelcome"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def setwelcome_command(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("Использование: /setwelcome [сообщение].")
    chat = await managers.chats.ensure_chat(message.chat.id)
    await managers.welcome_messages.set_message(
        chat.id, command.args, message.from_user.id
    )
    return await message.answer(
        f"{await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True)} успешно установил новое приветственное сообщение:\n{command.args}"
    )


@router.message(
    Command("resetwelcome"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def resetwelcome_command(message: Message, command: CommandObject):
    chat = await managers.chats.ensure_chat(message.chat.id)
    if not await managers.welcome_messages.get(chat.id):
        return await message.answer("Приветственное сообщение не установлено.")
    await managers.welcome_messages.remove_message(chat.id)
    return await message.answer(
        f"{await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True)} успешно удалил приветственное сообщение."
    )


@router.message(
    Command("getwelcome"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def getwelcome_command(message: Message, command: CommandObject):
    chat = await managers.chats.ensure_chat(message.chat.id)
    welcome = await managers.welcome_messages.get(chat.id)
    if not welcome:
        return await message.answer(
            "Приветственное сообщение не установлено, используйте команду /setwelcome [сообщение]."
        )
    return await message.answer(f"Текущее приветственное сообщение:\n{welcome.text}")


@router.message(
    Command("silence"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def silence_command(message: Message, command: CommandObject):
    chat_id = message.chat.id

    if (
        message.chat.type == ChatType.SUPERGROUP
        and getattr(message, "is_topic_message", False)
        and getattr(message, "message_thread_id", None)
    ):
        key = f"silence_topic:{message.message_thread_id}"
        scope = "этого топика"
    else:
        key = "silence_chat"
        scope = "этого чата"

    current = await managers.chat_settings.get(chat_id, key)
    if current:
        await managers.chat_settings.remove(chat_id, key)
        return await message.answer(f"Режим тишины отключён для {scope}.")
    else:
        await managers.chat_settings.set(chat_id, key, True)
        return await message.answer(f"Режим тишины включён для {scope}.")


@router.message(
    Command("setrole"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator, check_is_owner=True),
)
async def set_role(message: Message, command: CommandObject):
    help_text = "Использование: /setrole [1-3] ответом на сообщение."
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and not message.reply_to_message.is_topic_message
    ):
        target_user_id = message.reply_to_message.from_user.id
        if not command.args:
            return await message.answer(help_text)
        role_str = command.args.strip().lower()
    elif command.args:
        args = command.args.split(maxsplit=1)
        if len(args) < 2:
            return await message.answer(help_text)
        username = args[0].lstrip("@")
        role_str = args[1].strip().lower()
        target_user_id = await get_user_id_by_username(username)
        if not target_user_id:
            return await message.answer(f"Пользователь @{username} не найден.")

    else:
        return await message.answer(help_text)

    try:
        role = list(enums.Role)[int(role_str)]
    except ValueError:
        return await message.answer("Неверная роль. Введите от 1 до 3.")

    if target_user_id == message.bot.id:
        return await message.answer("Нельзя изменить роль бота.")

    target_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(target_user_id, message.chat.id),
            "level",
        )
        or enums.Role.user
    )
    if target_role == role:
        return await message.answer("У пользователя уже есть эти права.")

    author_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(message.from_user.id, message.chat.id),
            "level",
        )
        or enums.Role.user
    )
    is_owner = await managers.users.is_owner(message.from_user.id)
    if not is_owner:
        if target_user_id == message.from_user.id:
            return await message.answer("Нельзя изменить роль самому себе.")

        if role.level >= author_role.level:
            return await message.answer(
                "Вы не можете выдать роль большую или равную вашей."
            )

        target_role = await managers.user_roles.get(
            managers.user_roles.make_cache_key(target_user_id, message.chat.id), "level"
        )
        if target_role and target_role.level >= author_role.level:
            return await message.answer(
                "Нельзя изменить роль пользователя с ролью равной или выше вашей."
            )

    await managers.user_roles.add_role(
        target_user_id, message.chat.id, role, message.from_user.id
    )
    username = await get_user_display(
        target_user_id, message.bot, message.chat.id, need_a_tag=True
    )
    invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
    await message.bot.send_message(
        settings.logs.chat_id,
        f"""#setrole
➡️ Чат: {message.chat.title}\n
➡️ Пользователь: {(setter := await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True))}
➡️ Уровень прав: {author_role.value}
ℹ️ Действие: Выдал права
ℹ️ Права: {role.value}
➡️ Цель: {username}""",
        message_thread_id=settings.logs.access_levels_thread_id,
        reply_markup=keyboards.join(0, invite) if invite else None,
    )
    return await message.answer(
        f'{setter} выдал права "{role.value}" пользователю {username}'
    )


@router.message(
    Command("removerole"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def remove_role(message: Message, command: CommandObject):
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
            "Использование: /removerole @username или ответом на сообщение."
        )

    if target_user_id == message.from_user.id:
        return await message.answer("Нельзя удалить роль самому себе.")

    if target_user_id == message.bot.id:
        return await message.answer("Нельзя удалить роль бота.")

    is_owner = await managers.users.is_owner(message.from_user.id)
    author_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(message.from_user.id, message.chat.id),
            "level",
        )
        or enums.Role.user
    )

    target_role = await managers.user_roles.get(
        managers.user_roles.make_cache_key(target_user_id, message.chat.id), "level"
    )
    if not target_role:
        return await message.answer("У пользователя нет прав.")

    if target_role and target_role.level >= author_role.level and not is_owner:
        return await message.answer(
            "Нельзя удалить роль пользователя с ролью равной или выше вашей."
        )

    role = await managers.user_roles.remove_role(target_user_id, message.chat.id)
    username = await get_user_display(
        target_user_id, message.bot, message.chat.id, need_a_tag=True
    )
    invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
    await message.bot.send_message(
        settings.logs.chat_id,
        f"""#removerole
➡️ Чат: {message.chat.title}\n
➡️ Пользователь: {(setter := await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True))}
➡️ Уровень прав: {author_role.value}
ℹ️ Действие: Забрал права
ℹ️ Права: {role.value if role else "Пользователь"}
➡️ Цель: {username}""",
        message_thread_id=settings.logs.access_levels_thread_id,
        reply_markup=keyboards.join(0, invite) if invite else None,
    )
    return await message.answer(
        f'{setter} снял права "{role.value if role else "Пользователь"}" пользователю {username}'
    )


@router.message(
    Command("gban"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
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
                initiator_role = await managers.user_roles.get(
                    managers.user_roles.make_cache_key(
                        message.from_user.id, tg_chat_id
                    ),
                    "level",
                )
                target_role = (
                    await managers.user_roles.get(
                        managers.user_roles.make_cache_key(target_user_id, tg_chat_id),
                        "level",
                    )
                    or enums.Role.user
                )
                if initiator_role is not None and target_role >= initiator_role:
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
                    await managers.nicks.remove_nick(target_user_id, tg_chat_id)
                    await managers.user_roles.remove_role(target_user_id, tg_chat_id)
                    await message.bot.ban_chat_member(message.chat.id, target_user_id)
                    await message.bot.unban_chat_member(message.chat.id, target_user_id)
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

        banned_titles = []
        for tg_chat_id in banned:
            try:
                banned_titles.append((await message.bot.get_chat(tg_chat_id)).title)
            except TelegramForbiddenError:
                pass
        banned = "\n".join(
            [f"{k}. {i}" for k, i in enumerate(banned_titles[:25], start=1) if i]
        )
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


ALL_LIMITER = AsyncLimiter(10, 1)


@router.message(
    Command("all"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def all_(message: Message, command: CommandObject):
    async def send_with_retries(message, text, max_retries=5):
        for _ in range(max_retries):
            try:
                return await message.answer(text)

            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)

            except Exception as e:
                msg = str(e).lower()
                if "retry after" in msg or "retry in" in msg:
                    import re

                    m = re.search(r"(\d+)", msg[msg.find("retry") :])
                    if m:
                        delay = int(m.group(1))
                        await asyncio.sleep(delay + 1)
                        continue
                raise e

        raise RuntimeError("Too many retries, giving up.")

    try:
        users = [
            user.user.id
            async for user in managers.pyrogram_client.get_chat_members(message.chat.id)  # type: ignore
            if not user.user.is_bot and user.user.id not in settings.SILENT_TELEGRAM_IDS
        ]
    except Exception:
        users = [
            user.tg_user_id
            for user in await managers.user_roles.get_chat_roles(message.chat.id)
            if user.tg_user_id not in settings.SILENT_TELEGRAM_IDS
        ]
    call = [
        "".join(
            f'<a href="tg://user?id={user}">\u2060</a>'
            for user in users[i : i + 5]
            if user
        )
        for i in range(0, len(users), 5)
    ] or [""]
    from_name = await get_user_display(
        message.from_user.id, message.bot, message.chat.id, need_a_tag=True
    )
    rsn = f"\n💬 Причина вызова: {command.args}" if command.args else ""
    async with ALL_LIMITER:
        msgs = [
            await message.answer(
                f"❗️ Пользователь {from_name} вызвал Вас. [{len(users)}/{await message.bot.get_chat_member_count(message.chat.id)}]{call[0]}{rsn}"
            )
        ]
    if len(call) > 1:
        for i in range(1, len(call)):
            async with ALL_LIMITER:
                msgs.append(await send_with_retries(message, f"{call[i]}"))
    try:
        invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
        await message.bot.send_message(
            settings.logs.chat_id,
            f"""#all
    ➡️ Новое использование /all
    ➡️ Чат: {message.chat.title}
    ℹ️ Пользователь: {from_name}
    ℹ️ Текст: {message.html_text}
    ℹ️ Дата: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}""",
            message_thread_id=settings.logs.general_thread_id,
            reply_markup=keyboards.join(0, invite) if invite else None,
        )
    except Exception:
        pass
    return msgs
