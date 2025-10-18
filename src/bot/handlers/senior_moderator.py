from datetime import datetime, timedelta, timezone
from typing import Optional, Union

import loguru
from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import CommandObject
from aiogram.types import ChatPermissions, Message as AiogramMessage

from src.bot.filters import Command, RoleFilter
from src.bot.keyboards import callbackdata, keyboards
from src.bot.types import CallbackQuery, Message
from src.bot.utils import get_user_display, get_user_id_by_username, parse_duration
from src.core import enums, managers
from src.core.config import settings

router = Router()


@router.message(
    Command("snick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def set_nick(message: Message, command: CommandObject):
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and not message.reply_to_message.is_topic_message
    ):
        target_user_id = message.reply_to_message.from_user.id
        if not command.args:
            return await message.answer(
                "Использование: /snick [ник] ответом на сообщение."
            )
        nick = command.args.strip()
    elif command.args:
        args = command.args.split(maxsplit=1)
        if len(args) < 2:
            return await message.answer(
                "Использование: /snick @username [ник] или ответом на сообщение."
            )
        username = args[0].lstrip("@")
        nick = args[1].strip()
        target_user_id = await get_user_id_by_username(username)
        if not target_user_id:
            return await message.answer(f"Пользователь @{username} не найден.")
        if (
            await message.bot.get_chat_member(message.chat.id, target_user_id)
        ).status in [
            ChatMemberStatus.LEFT,
            ChatMemberStatus.KICKED,
            ChatMemberStatus.RESTRICTED,
        ]:
            return await message.answer("Данный пользователь не находится в беседе.")
    else:
        return await message.answer(
            "Использование: /snick @username [ник] или ответом на сообщение."
        )

    await managers.nicks.add_nick(
        target_user_id, message.chat.id, nick, message.from_user.id
    )
    username = await get_user_display(
        target_user_id, message.bot, message.chat.id, need_a_tag=True
    )
    setter = await get_user_display(
        message.from_user.id, message.bot, message.chat.id, need_a_tag=True
    )
    return await message.answer(
        f'{setter} установил новый ник <code>"{nick}"</code> пользователю {username}.'
    )


@router.message(
    Command("rnick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def remove_nick(message: Message, command: CommandObject):
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
            "Использование: /rnick @username или ответом на сообщение."
        )

    nick = await managers.nicks.remove_nick(target_user_id, message.chat.id)
    username = await get_user_display(target_user_id, message.bot, message.chat.id, need_a_tag=True)
    setter = await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True)
    return await message.answer(f"{setter} удалил никнейм{f' "{nick.nick}"' if nick else ''} у пользователя {username}")


@router.message(
    Command("mute"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def mute_user(message: Message, command: CommandObject):
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and not message.reply_to_message.is_topic_message
    ):
        target_user_id = message.reply_to_message.from_user.id
        args = command.args.split(maxsplit=1) if command.args else []
        duration = parse_duration(args[0]) if args else timedelta(days=400)
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
                duration = timedelta(days=400)
                reason = args[1] if len(args) > 1 else None
        except Exception:
            return await message.answer(
                "Использование: /mute @username [время] [причина] или ответом на сообщение."
            )

        target_user_id = await get_user_id_by_username(username)
        if not target_user_id:
            return await message.answer(f"Пользователь @{username} не найден.")

    if not duration:
        return await message.answer(
            "Неверный формат времени. Используйте: 10m, 1h, 1d."
        )

    if target_user_id == message.from_user.id:
        return await message.answer("Нельзя замутить самого себя.")

    if target_user_id == message.bot.id:
        return await message.answer("Нельзя замутить бота.")

    target_member = await message.bot.get_chat_member(message.chat.id, target_user_id)
    if target_member.status in ["creator", "administrator"]:
        return await message.answer("Нельзя замутить администратора чата.")

    initiator_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(message.from_user.id, message.chat.id),
            "level",
        )
        or enums.Role.user
    )
    target_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(target_user_id, message.chat.id), "level"
        )
        or enums.Role.user
    )
    if target_role >= initiator_role:
        return await message.answer(
            "Вы не можете замутить пользователя с равной или выше ролью."
        )

    start_at = datetime.now(timezone.utc)
    end_at = start_at + duration

    await message.bot.restrict_chat_member(
        message.chat.id,
        target_user_id,
        ChatPermissions(can_send_messages=False),
        until_date=end_at,
    )

    await managers.mutes.add_mute(
        target_user_id,
        message.chat.id,
        start_at=start_at,
        end_at=end_at,
        reason=reason,
        created_by_tg_id=message.from_user.id,
        active=True,
        auto_unmute=True,
    )
    username = await get_user_display(target_user_id, message.bot, message.chat.id)
    msk_tz = timezone(timedelta(hours=3))
    end_at_msk = end_at.astimezone(msk_tz)
    end_at_text = (
        f"до {end_at_msk.strftime('%d.%m.%Y %H:%M')}"
        if end_at - datetime.now(timezone.utc) < timedelta(days=3650)
        else "навсегда"
    )

    invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
    await message.bot.send_message(
        settings.logs.chat_id,
        f"""#mute
➡️ Чат: {message.chat.title}\n
➡️ Пользователь: {(setter := await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True))}
➡️ Уровень прав: {initiator_role.value}
ℹ️ Действие: Замутил пользователя
ℹ️ Срок: {end_at_text}
ℹ️ Причина: {reason or "Не указана"}
➡️ Цель: {username}""",
        message_thread_id=settings.logs.punishments_thread_id,
        reply_markup=keyboards.join(0, invite) if invite else None,
    )
    return await message.answer(
        f"{setter} замутил {username} {end_at_text}{f' по причине {reason}' if reason else ''}",
        reply_markup=keyboards.mute_actions(message.from_user.id, target_user_id, True),
    )


@router.message(
    Command("unmute"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def unmute_user(message: Message, command: CommandObject):
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
            "Использование: /unmute @username или ответом на сообщение."
        )

    initiator_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(message.from_user.id, message.chat.id),
            "level",
        )
        or enums.Role.user
    )
    target_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(target_user_id, message.chat.id), "level"
        )
        or enums.Role.user
    )
    if target_role >= initiator_role:
        return await message.answer(
            "Вы не можете размутить пользователя с равной или выше ролью."
        )
    if (await message.bot.get_chat_member(message.chat.id, target_user_id)).status in [
        ChatMemberStatus.LEFT,
        ChatMemberStatus.KICKED,
        ChatMemberStatus.RESTRICTED,
    ]:
        return await message.answer("Данный пользователь не находится в беседе.")

    await message.bot.restrict_chat_member(
        message.chat.id,
        target_user_id,
        ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        ),
    )

    await managers.mutes.remove_mute(target_user_id, message.chat.id)
    username = await get_user_display(target_user_id, message.bot, message.chat.id)
    invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
    await message.bot.send_message(
        settings.logs.chat_id,
        f"""#unmute
➡️ Чат: {message.chat.title}\n
➡️ Пользователь: {(initiator := await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True))}
➡️ Уровень прав: {initiator_role.value}
ℹ️ Действие: Размутил пользователя
➡️ Цель: {username}""",
        message_thread_id=settings.logs.punishments_thread_id,
        reply_markup=keyboards.join(0, invite) if invite else None,
    )
    return await message.answer(f"{initiator} снял мут с пользователя {username}.")


@router.callback_query(callbackdata.MuteAction.filter())
async def mute_callback(query: CallbackQuery, callback_data: callbackdata.MuteAction):
    duration = parse_duration(callback_data.duration)
    if not duration:
        return await query.answer("Ошибка времени.", show_alert=True)

    if callback_data.user_id == query.from_user.id:
        return await query.answer("Нельзя замутить самого себя.", show_alert=True)

    if callback_data.user_id == query.bot.id:
        return await query.answer("Нельзя замутить бота.", show_alert=True)

    target_member = await query.bot.get_chat_member(
        query.message.chat.id, callback_data.user_id
    )
    if target_member.status in ["creator", "administrator"]:
        return await query.answer("Нельзя замутить администратора.", show_alert=True)

    existing_mute = await managers.mutes.get(
        callback_data.user_id, query.message.chat.id
    )
    reason = existing_mute.reason if existing_mute else None

    start_at = datetime.now(timezone.utc)
    end_at = start_at + duration

    await query.bot.restrict_chat_member(
        query.message.chat.id,
        callback_data.user_id,
        ChatPermissions(can_send_messages=False),
        until_date=end_at,
    )

    await managers.mutes.add_mute(
        callback_data.user_id,
        query.message.chat.id,
        start_at=start_at,
        end_at=end_at,
        reason=reason,
        created_by_tg_id=query.from_user.id,
        active=True,
        auto_unmute=True,
    )

    username = await get_user_display(
        callback_data.user_id, query.bot, query.message.chat.id
    )
    msk_tz = timezone(timedelta(hours=3))
    end_at_msk = end_at.astimezone(msk_tz)
    end_at_text = (
        f"до {end_at_msk.strftime('%d.%m.%Y %H:%M')}"
        if end_at - datetime.now(timezone.utc) < timedelta(days=3650)
        else "навсегда"
    )
    await query.message.edit_text(
        f"Пользователь {username} замучен {end_at_text}.{f' Причина: {reason}' if reason else ''}",
        reply_markup=keyboards.mute_actions(
            query.from_user.id, callback_data.user_id, True
        ),
    )


@router.callback_query(callbackdata.UnmuteAction.filter())
async def unmute_callback(
    query: CallbackQuery, callback_data: callbackdata.UnmuteAction
):
    await query.bot.restrict_chat_member(
        query.message.chat.id,
        callback_data.user_id,
        ChatPermissions(
            can_send_messages=True,
            can_send_media_messages=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        ),
    )

    await managers.mutes.remove_mute(callback_data.user_id, query.message.chat.id)
    username = await get_user_display(
        callback_data.user_id, query.bot, query.message.chat.id
    )
    await query.message.edit_text(
        f"Мут снят с пользователя {username}.",
        reply_markup=keyboards.mute_actions(
            callback_data.user_id, callback_data.user_id, False
        ),
    )


@router.message(
    Command("pin"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def pin_message(message: Message):
    if not message.reply_to_message:
        return await message.answer("Использование: /pin ответом на сообщение.")

    await message.bot.pin_chat_message(
        message.chat.id,
        message.reply_to_message.message_id,
        disable_notification=True,
    )
    await managers.message_pins.add_pin(
        message.chat.id,
        message.reply_to_message.message_id,
        message.from_user.id,
    )
    invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
    await message.bot.send_message(
        settings.logs.chat_id,
        f"""#pin
➡️ Новый закреп от {await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True)}
➡️ Чат: {message.chat.title}
ℹ️ Сообщение: <a href="{message.reply_to_message.get_url()}">КЛИК</a>
ℹ️ Дата: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}""",
        message_thread_id=settings.logs.general_thread_id,
        reply_markup=keyboards.join(0, invite) if invite else None,
    )
    return await message.answer(f"{await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True)} закрепил сообщение.")


@router.message(
    Command("unpin"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def unpin_message(message: Message):
    if not message.reply_to_message:
        return await message.answer("Использование: /unpin ответом на сообщение.")

    if not await message.bot.unpin_chat_message(
        chat_id=message.chat.id,
        message_id=message.reply_to_message.message_id,
    ):
        return await message.answer("Данное сообщение не закреплено.")
    return await message.answer(f"{await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True)} открепил сообщение.")


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
    username = await get_user_display(target_user_id, message.bot, message.chat.id, need_a_tag=True)
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
        f"{setter} выдал права \"{role.value}\" пользователю {username}"
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
    username = await get_user_display(target_user_id, message.bot, message.chat.id, need_a_tag=True)
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
        f"{setter} снял права \"{role.value if role else "Пользователь"}\" пользователю {username}")


@router.message(
    Command("kick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
@router.callback_query(callbackdata.UserStats.filter(F.button == "kick"))
async def kick_command(message_or_query: Union[Message, CallbackQuery], command: Optional[CommandObject] = None, callback_data: Optional[callbackdata.UserStats] = None):
    if isinstance(message_or_query, AiogramMessage):
        if not command:
            return
        message = message_or_query
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
            return await message.answer("Использование: /kick @username")
    else:
        if not callback_data:
            return
        query = message_or_query
        message = query.message
        user_id = callback_data.user_id
        member = await message_or_query.bot.get_chat_member(query.message.chat.id, user_id)
        if member.status in [ChatMemberStatus.KICKED, ChatMemberStatus.LEFT, ChatMemberStatus.RESTRICTED]:
            return await message_or_query.answer("Пользователь уже исключен.")
        username = member.user.username
        reason = None

    try:
        target = await message_or_query.bot.get_chat_member(message.chat.id, user_id)
        bot_member = await message_or_query.bot.get_chat_member(message.chat.id, message_or_query.bot.id)

        if target.status in ("creator", "administrator"):
            return await message_or_query.answer("Невозможно кикнуть администратора.")

        if (
            bot_member.status not in ("creator", "administrator")
            or not hasattr(bot_member, "can_restrict_members")
            or not bot_member.can_restrict_members  # type: ignore
        ):
            return await message_or_query.answer("У бота нет прав на кик пользователей.")

        initiator_role = (
            await managers.user_roles.get(
                managers.user_roles.make_cache_key(
                    message_or_query.from_user.id, message.chat.id
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
            return await message_or_query.answer(
                "Вы не можете кикнуть пользователя с равной или выше ролью."
            )

        print(message.chat.id)
        await message_or_query.bot.ban_chat_member(message.chat.id, user_id)
        await message_or_query.bot.unban_chat_member(message.chat.id, user_id)
        invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
        await message_or_query.bot.send_message(
            settings.logs.chat_id,
            f"""#kick
➡️ Чат: {message.chat.title}\n
➡️ Пользователь: {(setter := await get_user_display(message_or_query.from_user.id, message_or_query.bot, message.chat.id, need_a_tag=True))}
➡️ Уровень прав: {initiator_role.value}
ℹ️ Действие: Исключил из чата
ℹ️ Причина: {reason or "Не указана"}
➡️ Цель: @{username}""",
            message_thread_id=settings.logs.punishments_thread_id,
            reply_markup=keyboards.join(0, invite) if invite else None,
        )
        return await message_or_query.answer(
            f"{setter} кикнул @{username} из чата{f' по причине: {reason}' if reason else ''}"
        )
    except Exception:
        loguru.logger.exception("admin.kick handler exception:")
        return await message_or_query.answer("Неизвестная ошибка.")


@router.message(
    Command("ban"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
@router.callback_query(callbackdata.UserStats.filter(F.button == "ban"))
async def ban_command(message_or_query: Union[Message, CallbackQuery], command: Optional[CommandObject] = None, callback_data: Optional[callbackdata.UserStats] = None):
    try:
        if isinstance(message_or_query, AiogramMessage):
            if not command:
                return
            message = message_or_query
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
                        duration = timedelta(days=400)
                        reason = args[1] if len(args) > 1 else None
                except Exception:
                    return await message.answer(
                        "Использование: /ban @username [время] [причина] или ответом на сообщение."
                    )

                target_user_id = await get_user_id_by_username(username)
                if not target_user_id:
                    return await message.answer(f"Пользователь @{username} не найден.")

            if not duration:
                return await message.answer(
                    "Неверный формат времени. Используйте: 10m, 1h, 1d."
                )
        else:
            if not callback_data:
                return
            query = message_or_query
            message = query.message
            target_user_id = callback_data.user_id
            member = await message_or_query.bot.get_chat_member(query.message.chat.id, target_user_id)
            if member.status in [ChatMemberStatus.RESTRICTED]:
                return await message_or_query.answer("Пользователь уже забанен.")
            username = member.user.username
            duration = timedelta(days=3650)
            reason = None

        if target_user_id == message_or_query.from_user.id:
            return await message_or_query.answer("Нельзя забанить самого себя.")

        if target_user_id == message_or_query.bot.id:
            return await message_or_query.answer("Нельзя забанить бота.")

        target_member = await message_or_query.bot.get_chat_member(
            message.chat.id, target_user_id
        )
        if target_member.status in ("creator", "administrator"):
            return await message_or_query.answer("Нельзя забанить администратора чата.")

        initiator_role = (
            await managers.user_roles.get(
                managers.user_roles.make_cache_key(
                    message_or_query.from_user.id, message.chat.id
                ),
                "level",
            )
            or enums.Role.user
        )
        target_role = (
            await managers.user_roles.get(
                managers.user_roles.make_cache_key(target_user_id, message.chat.id),
                "level",
            )
            or enums.Role.user
        )
        if target_role >= initiator_role:
            return await message_or_query.answer(
                "Вы не можете забанить пользователя с равной или выше ролью."
            )

        start_at = datetime.now(timezone.utc)
        end_at = start_at + duration

        await managers.users.edit(target_user_id, banned_until=end_at)

        try:
            await managers.global_bans.add_ban(
                target_user_id,
                message.chat.id,
                start_at=start_at,
                end_at=end_at,
                reason=reason,
                created_by_tg_id=message_or_query.from_user.id,
                active=True,
                auto_unban=True,
            )
        except Exception:
            pass

        username = await get_user_display(target_user_id, message_or_query.bot, message.chat.id)
        msk_tz = timezone(timedelta(hours=3))
        end_at_msk = end_at.astimezone(msk_tz)
        end_at_text = (
            f"до {end_at_msk.strftime('%d.%m.%Y %H:%M')}"
            if end_at - datetime.now(timezone.utc) < timedelta(days=3650)
            else "навсегда"
        )
        setter_name = await get_user_display(
            message_or_query.from_user.id, message_or_query.bot, message.chat.id
        )
        invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
        await message_or_query.bot.send_message(
            settings.logs.chat_id,
            f"""#ban
➡️ Чат: {message.chat.title}\n
➡️ Пользователь: {setter_name}
➡️ Уровень прав: {initiator_role.value}
ℹ️ Действие: Забанил пользователя
ℹ️ Срок: {end_at_text}
ℹ️ Причина: {reason or "Не указана"}
➡️ Цель: {username}""",
            message_thread_id=settings.logs.punishments_thread_id,
            reply_markup=keyboards.join(0, invite) if invite else None,
        )
        return await message_or_query.answer(
            f"{setter_name} забанил пользователя {username} {end_at_text}.{f' Причина: {reason}' if reason else ''}"
        )
    except Exception:
        loguru.logger.exception("admin.ban handler exception:")
        return await message_or_query.answer("Неизвестная ошибка.")


@router.message(
    Command("unban"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def unban_command(message: Message, command: CommandObject):
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
            "Использование: /unban @username или ответом на сообщение."
        )

    banned_until = await managers.users.get(target_user_id, "banned_until")
    if not banned_until or banned_until < datetime.now(timezone.utc):
        return await message.answer("Данный пользователь не забанен.")

    initiator_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(message.from_user.id, message.chat.id),
            "level",
        )
        or enums.Role.user
    )
    target_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(target_user_id, message.chat.id), "level"
        )
        or enums.Role.user
    )
    if target_role >= initiator_role:
        return await message.answer(
            "Вы не можете разбанить пользователя с равной или выше ролью."
        )

    try:
        await message.bot.unban_chat_member(message.chat.id, target_user_id)
        await managers.users.edit(target_user_id, banned_until=None)
        try:
            await managers.global_bans.remove_ban(target_user_id, message.chat.id)
        except Exception:
            pass
        username = await get_user_display(target_user_id, message.bot, message.chat.id)
        setter_name = await get_user_display(
            message.from_user.id, message.bot, message.chat.id
        )
        invite = await managers.chats.get(message.chat.id, "infinite_invite_link")
        await message.bot.send_message(
            settings.logs.chat_id,
            f"""#unban
➡️ Чат: {message.chat.title}\n
➡️ Пользователь: {setter_name}
➡️ Уровень прав: {initiator_role.value}
ℹ️ Действие: Разбанил пользователя
➡️ Цель: {username}""",
            message_thread_id=settings.logs.punishments_thread_id,
            reply_markup=keyboards.join(0, invite) if invite else None,
        )
        return await message.answer(
            f"{setter_name} разбанил пользователя {username} в этом чате."
        )
    except Exception:
        loguru.logger.exception("admin.unban handler exception:")
        return await message.answer("Неизвестная ошибка.")
