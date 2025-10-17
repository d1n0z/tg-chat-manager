import re
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandObject
from aiogram.types import ChatPermissions

from src.bot.filters import Command, RoleFilter
from src.bot.keyboards import callbackdata, keyboards
from src.bot.types import CallbackQuery, Message
from src.bot.utils import get_user_display, get_user_id_by_username
from src.core import enums, managers

router = Router()


def _parse_duration(duration_str: str) -> timedelta | None:
    match = re.match(r"^(\d+)([mhd])$", duration_str.lower())
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    if unit == "m":
        return timedelta(minutes=value)
    elif unit == "h":
        return timedelta(hours=value)
    elif unit == "d":
        return timedelta(days=value)
    return None


@router.message(
    Command("snick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def set_nick(message: Message, command: CommandObject):
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
        if not command.args:
            await message.answer("Использование: /snick [ник] ответом на сообщение.")
            return
        nick = command.args.strip()
    elif command.args:
        args = command.args.split(maxsplit=1)
        if len(args) < 2:
            await message.answer(
                "Использование: /snick @username [ник] или ответом на сообщение."
            )
            return
        username = args[0].lstrip("@")
        nick = args[1].strip()
        target_user_id = await get_user_id_by_username(username)
        if not target_user_id:
            await message.answer(f"Пользователь @{username} не найден.")
            return
    else:
        await message.answer(
            "Использование: /snick @username [ник] или ответом на сообщение."
        )
        return

    await managers.nicks.add_nick(
        target_user_id, message.chat.id, nick, message.from_user.id
    )
    username = await get_user_display(target_user_id, message.bot, message.chat.id)
    await message.answer(
        f"Ник установлен пользователю {username}: <code>{nick}</code>."
    )


@router.message(
    Command("rnick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def remove_nick(message: Message, command: CommandObject):
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
    elif command.args:
        username = command.args.lstrip("@")
        target_user_id = await get_user_id_by_username(username)
        if not target_user_id:
            await message.answer(f"Пользователь @{username} не найден.")
            return
    else:
        await message.answer(
            "Использование: /rnick @username или ответом на сообщение."
        )
        return

    await managers.nicks.remove_nick(target_user_id, message.chat.id)
    username = await get_user_display(target_user_id, message.bot, message.chat.id)
    await message.answer(f"Ник удалён у пользователя {username}.")


@router.message(
    Command("mute"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def mute_user(message: Message, command: CommandObject):
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
        args = command.args.split(maxsplit=1) if command.args else []
        duration = _parse_duration(args[0]) if args else timedelta(days=400)
        reason = args[1] if len(args) > 1 else None
    else:
        try:
            if not command.args:
                raise ValueError
            args = command.args.split(maxsplit=2)
            username = args[0].lstrip("@")
            if len(args) > 1 and (duration := _parse_duration(args[1])):
                reason = args[2] if len(args) > 2 else None
            else:
                duration = timedelta(days=400)
                reason = args[1] if len(args) > 1 else None
        except Exception:
            await message.answer(
                "Использование: /mute @username [время] [причина] или ответом на сообщение."
            )
            return

        target_user_id = await get_user_id_by_username(username)
        if not target_user_id:
            await message.answer(f"Пользователь @{username} не найден.")
            return

    if not duration:
        await message.answer("Неверный формат времени. Используйте: 10m, 1h, 1d.")
        return

    if target_user_id == message.from_user.id:
        await message.answer("Нельзя замутить самого себя.")
        return

    if target_user_id == message.bot.id:
        await message.answer("Нельзя замутить бота.")
        return

    target_member = await message.bot.get_chat_member(message.chat.id, target_user_id)
    if target_member.status in ["creator", "administrator"]:
        await message.answer("Нельзя замутить администратора чата.")
        return

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
        if end_at - datetime.now(timezone.utc) < timedelta(days=365)
        else "навсегда"
    )
    await message.answer(
        f"Пользователь {username} замучен {end_at_text}.{f' Причина: {reason}' if reason else ''}",
        reply_markup=keyboards.mute_actions(message.from_user.id, target_user_id),
    )


@router.message(
    Command("unmute"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def unmute_user(message: Message, command: CommandObject):
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
    elif command.args:
        username = command.args.lstrip("@")
        target_user_id = await get_user_id_by_username(username)
        if not target_user_id:
            await message.answer(f"Пользователь @{username} не найден.")
            return
    else:
        await message.answer(
            "Использование: /unmute @username или ответом на сообщение."
        )
        return

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
    await message.answer(f"Мут снят с пользователя {username}.")


@router.callback_query(callbackdata.MuteAction.filter())
async def mute_callback(query: CallbackQuery, callback_data: callbackdata.MuteAction):
    duration = _parse_duration(callback_data.duration)
    if not duration:
        await query.answer("Ошибка времени.", show_alert=True)
        return

    if callback_data.user_id == query.from_user.id:
        await query.answer("Нельзя замутить самого себя.", show_alert=True)
        return

    if callback_data.user_id == query.bot.id:
        await query.answer("Нельзя замутить бота.", show_alert=True)
        return

    target_member = await query.bot.get_chat_member(
        query.message.chat.id, callback_data.user_id
    )
    if target_member.status in ["creator", "administrator"]:
        await query.answer("Нельзя замутить администратора.", show_alert=True)
        return

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
        if end_at - datetime.now(timezone.utc) < timedelta(days=365)
        else "навсегда"
    )
    await query.message.edit_text(
        f"Пользователь {username} замучен {end_at_text}.{f' Причина: {reason}' if reason else ''}",
        reply_markup=keyboards.mute_actions(query.from_user.id, callback_data.user_id),
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
        reply_markup=keyboards.mute_actions(callback_data.user_id, callback_data.user_id),
    )


@router.message(
    Command("pin"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def pin_message(message: Message):
    if not message.reply_to_message:
        await message.answer("Использование: /pin ответом на сообщение.")
        return

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
    await message.answer("Сообщение закреплено.")


@router.message(
    Command("unpin"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def unpin_message(message: Message):
    if not message.reply_to_message:
        await message.answer("Использование: /unpin ответом на сообщение.")
        return

    await message.bot.unpin_chat_message(
        chat_id=message.chat.id,
        message_id=message.reply_to_message.message_id,
    )
    await message.answer("Сообщение откреплено.")


@router.message(
    Command("setrole"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def set_role(message: Message, command: CommandObject):
    allowed_roles = [role.value for role in enums.Role]
    help_text = (
        f"Использование: /setrole [{'|'.join(allowed_roles)}] ответом на сообщение."
    )
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
        if not command.args:
            await message.answer(help_text)
            return
        role_str = command.args.strip().lower()
    elif command.args:
        args = command.args.split(maxsplit=1)
        if len(args) < 2:
            await message.answer(help_text)
            return
        username = args[0].lstrip("@")
        role_str = args[1].strip().lower()
        target_user_id = await get_user_id_by_username(username)
        if not target_user_id:
            await message.answer(f"Пользователь @{username} не найден.")
            return
    else:
        await message.answer(help_text)
        return

    try:
        role = enums.Role(role_str)
    except ValueError:
        await message.answer(
            f"Неверная роль. Доступны только: {', '.join(allowed_roles)}."
        )
        return

    is_owner = await managers.users.is_owner(message.from_user.id)
    author_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(message.from_user.id, message.chat.id),
            "level",
        )
        or enums.Role.user
    )

    if role == enums.Role.admin and not is_owner:
        await message.answer("Только владелец может выдавать роль admin.")
        return

    if (
        role == enums.Role.senior_moderator
        and author_role.level < enums.Role.admin.level
    ):
        await message.answer(
            "Только администратор может выдавать роль senior_moderator."
        )
        return

    if (
        role.level > enums.Role.moderator.level
        and author_role.level < enums.Role.admin.level
        and not is_owner
    ):
        await message.answer("Вы можете выдавать только роли user и moderator.")
        return

    if target_user_id == message.from_user.id:
        await message.answer("Нельзя изменить роль самому себе.")
        return

    if target_user_id == message.bot.id:
        await message.answer("Нельзя изменить роль бота.")
        return

    target_role = await managers.user_roles.get(
        managers.user_roles.make_cache_key(target_user_id, message.chat.id), "level"
    )
    if target_role and target_role.level >= author_role.level and not is_owner:
        await message.answer(
            "Нельзя изменить роль пользователя с ролью равной или выше вашей."
        )
        return

    await managers.user_roles.add_role(
        target_user_id, message.chat.id, role, message.from_user.id
    )
    username = await get_user_display(target_user_id, message.bot, message.chat.id)
    await message.answer(f"Роль {role.value} установлена пользователю {username}.")


@router.message(
    Command("removerole"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.senior_moderator),
)
async def remove_role(message: Message, command: CommandObject):
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
    elif command.args:
        username = command.args.lstrip("@")
        target_user_id = await get_user_id_by_username(username)
        if not target_user_id:
            await message.answer(f"Пользователь @{username} не найден.")
            return
    else:
        await message.answer(
            "Использование: /removerole @username или ответом на сообщение."
        )
        return

    if target_user_id == message.from_user.id:
        await message.answer("Нельзя удалить роль самому себе.")
        return

    if target_user_id == message.bot.id:
        await message.answer("Нельзя удалить роль бота.")
        return

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
    if target_role and target_role.level >= author_role.level and not is_owner:
        await message.answer(
            "Нельзя удалить роль пользователя с ролью равной или выше вашей."
        )
        return

    await managers.user_roles.remove_role(target_user_id, message.chat.id)
    username = await get_user_display(target_user_id, message.bot, message.chat.id)
    await message.answer(f"Роль удалена у пользователя {username}.")
