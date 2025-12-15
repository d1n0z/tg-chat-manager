import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

import loguru
from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import CommandObject
from aiogram.types import ChatPermissions
from aiogram.types import Message as AiogramMessage

from src.bot.filters import Command, RoleFilter
from src.bot.keyboards import callbackdata, keyboards
from src.bot.types import CallbackQuery, Message
from src.bot.utils import get_user_display, get_user_id_by_username, parse_duration
from src.core import enums, managers
from src.core.config import settings

router = Router()


@router.message(
    Command("pin"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
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
    return await message.answer(
        f"{await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True)} закрепил сообщение."
    )


@router.message(
    Command("unpin"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def unpin_message(message: Message):
    if not message.reply_to_message:
        return await message.answer("Использование: /unpin ответом на сообщение.")

    if not await message.bot.unpin_chat_message(
        chat_id=message.chat.id,
        message_id=message.reply_to_message.message_id,
    ):
        return await message.answer("Данное сообщение не закреплено.")
    return await message.answer(
        f"{await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True)} открепил сообщение."
    )


def get_sort_key(item: str) -> str:
    item = item.strip()

    match = re.search(r"\|\s*([^\n]+)", item)
    if match:
        return match.group(1).strip()

    match = re.search(r"<a [^>]*>([^<]+)</a>", item)
    if match:
        return match.group(1).strip()

    match = re.search(r"(?:•|\d+\.)?\s*(?:ID_|@)?([A-Za-z0-9_]+)", item)
    if match:
        return match.group(1).strip()

    match = re.search(r"(?:•|\d+\.)?\s*([^\n]+)", item)
    if match:
        return match.group(1).strip()

    return item


async def _prepare_nick_list(
    chat_id: int, page: int, bot: Bot, bot_chat_id: int, no_nick_list
):
    nicks = await managers.nicks.get_chat_nicks(chat_id)
    if no_nick_list:
        have_nicks = [i.tg_user_id for i in nicks]
        list_data = sorted(
            [
                (
                    "",
                    await get_user_display(
                        user.user.id, bot, bot_chat_id, need_a_tag=True, no_tag=True
                    ),
                )
                async for user in managers.pyrogram_client.get_chat_members(chat_id if str(chat_id).startswith('-100') else f'-100{chat_id}')  # type: ignore
                if user.user.id not in have_nicks and not user.user.is_bot
            ],
            key=lambda i: i[1],
        )
    else:
        list_data = sorted(
            [
                (
                    f" | {nick_obj.nick}",
                    await get_user_display(
                        nick_obj.tg_user_id,
                        bot,
                        bot_chat_id,
                        need_a_tag=True,
                        no_tag=True,
                    ),
                )
                for nick_obj in nicks
            ],
            key=lambda i: i[0][3:],
        )

    per_page = 25
    total_pages = (len(list_data) - 1) // per_page if list_data else 0
    page_data = list_data[page * per_page : (page + 1) * per_page]

    results = []
    for nick_str, username in page_data:
        results.append(f"{username}{nick_str}")

    return (
        len(list_data),
        [f"[{k}]. {i}" for k, i in enumerate(results, start=(page * per_page) + 1)],
        page,
        total_pages,
    )


@router.message(
    Command("nlist"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def nick_list(message: Message, command: CommandObject):
    nicks = await managers.nicks.get_chat_nicks(message.chat.id)
    if not nicks:
        return await message.answer("В этом чате нет пользователей с никами.", reply_markup=keyboards.nick_list_paginate(
            message.from_user.id, 0, 0, message.chat.id, False
        ))

    total, results, page, total_pages = await _prepare_nick_list(
        message.chat.id, 0, message.bot, message.chat.id, False
    )

    return await message.answer(
        f"Список пользователей с никами ({total}):\n\n" + "\n".join(results),
        reply_markup=keyboards.nick_list_paginate(
            message.from_user.id, page, total_pages, message.chat.id, False
        ),
    )


@router.callback_query(callbackdata.NickListPaginate.filter())
async def nick_list_page(
    query: CallbackQuery, callback_data: callbackdata.NickListPaginate
):
    total, results, page, total_pages = await _prepare_nick_list(
        callback_data.chat_id,
        callback_data.page,
        query.bot,
        query.message.chat.id,
        callback_data.no_nick_mode,
    )

    await query.message.edit_text(
        f"Список пользователей с никами ({total}):\n\n" + "\n".join(results),
        reply_markup=keyboards.nick_list_paginate(
            query.from_user.id,
            page,
            total_pages,
            callback_data.chat_id,
            callback_data.no_nick_mode,
        ),
    )


@router.message(
    Command("clear", "cl"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def clear_messages(message: Message, command: CommandObject):
    message_ids = []
    if message.reply_to_message:
        message_ids = [message.reply_to_message.message_id]
    elif not command.args:
        return await message.answer(
            "Использование: /clear [количество(1-100)] или ответом на сообщение."
        )

    try:
        if not message_ids and (
            not command.args.isdigit()  # type: ignore
            or (count := int(command.args)) not in range(1, 101)  # type: ignore
        ):
            return await message.answer(
                "Количество должно быть целым числом от 1 до 100."
            )

        if not message_ids:
            message_ids = await managers.message_logs.get_last_n_messages(
                message.chat.id, count + 1, message.message_thread_id
            )
        if message_ids:
            await message.bot.delete_messages(message.chat.id, message_ids)
        if message.from_user.full_name:
            name = f'<a href="tg://user?id={message.from_user.id}">{message.from_user.full_name}</a>'
        elif message.from_user.username:
            name = f"@{message.from_user.username}"
        else:
            name = f'<a href="tg://user?id={message.from_user.id}">ID_{message.from_user.id}</a>'
        return await message.answer(
            f"Пользователь {name} очистил {f'{command.args} сообщений' if len(message_ids) > 1 else 'сообщение'}."
        )
    except Exception:
        return await message.answer("Ошибка при удалении сообщений.")


@router.message(
    Command("gbynick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def get_by_nick(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("Использование: /gbynick [ник].")

    nick = command.args.strip()
    nick_records = await managers.nicks.get_by_nick(message.chat.id, nick)
    if not nick_records:
        return await message.answer(f"Пользователи с ником '{nick}' не найдены.")

    per_page = 25
    total_pages = (len(nick_records) - 1) // per_page if nick_records else 0
    page_records = nick_records[:per_page]

    results = []
    for nick_str, tg_user_id in page_records:
        username = await get_user_display(
            tg_user_id, message.bot, message.chat.id, need_a_tag=True
        )
        results.append(f"{nick_str} | {username}")

    return await message.answer(
        f"<b>Найдено: {len(nick_records)}</b>\n\n"
        + "\n".join([f"[{k}]. {i}" for k, i in enumerate(results, start=1)]),
        reply_markup=keyboards.gbynick_paginate(
            message.from_user.id, 0, total_pages, message.chat.id, nick
        )
        if total_pages > 0
        else None,
    )


@router.message(
    Command("gnick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def get_nick(message: Message, command: CommandObject):
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
            return await message.answer(f"Пользователь {username} не найден.")
    else:
        return await message.answer(
            "Использование: /gnick @username или ответом на сообщение."
        )

    nick = await managers.nicks.get(
        managers.nicks.make_cache_key(target_user_id, message.chat.id), "nick"
    )
    username = await get_user_display(target_user_id, message.bot, message.chat.id)
    if not nick:
        return await message.answer(f"У пользователя {username} нет ника.")

    return await message.answer(f"Ник пользователя {username}: <code>{nick}</code>.")


@router.callback_query(callbackdata.GByNickPaginate.filter())
async def gbynick_page(
    query: CallbackQuery, callback_data: callbackdata.GByNickPaginate
):
    nick_records = await managers.nicks.get_by_nick(
        callback_data.chat_id, callback_data.nick
    )
    if not nick_records:
        return await query.answer("Пользователи не найдены.", show_alert=True)

    per_page = 25
    total_pages = (len(nick_records) - 1) // per_page if nick_records else 0
    page = callback_data.page
    page_records = nick_records[page * per_page : (page + 1) * per_page]

    results = []
    for nick_str, tg_user_id in page_records:
        username = await get_user_display(
            tg_user_id, query.bot, query.message.chat.id, need_a_tag=True
        )
        results.append(f"{nick_str} | {username}")

    await query.message.edit_text(
        f"<b>Найдено: {len(nick_records)}</b>\n\n"
        + "\n".join(
            [f"[{k}]. {i}" for k, i in enumerate(results, start=(page * per_page) + 1)]
        ),
        reply_markup=keyboards.gbynick_paginate(
            query.from_user.id,
            page,
            total_pages,
            callback_data.chat_id,
            callback_data.nick,
        )
        if total_pages > 0
        else None,
    )


@router.message(
    Command("snick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
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
    RoleFilter(enums.Role.moderator),
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
    username = await get_user_display(
        target_user_id, message.bot, message.chat.id, need_a_tag=True
    )
    setter = await get_user_display(
        message.from_user.id, message.bot, message.chat.id, need_a_tag=True
    )
    return await message.answer(
        f"{setter} удалил никнейм{f' "{nick.nick}"' if nick else ''} у пользователя {username}"
    )


@router.message(
    Command("mute"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def mute_user(message: Message, command: CommandObject):
    if (
        message.reply_to_message
        and message.reply_to_message.from_user
        and not message.reply_to_message.is_topic_message
        and len((command.args or "").split(maxsplit=2)) < 3
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
    try:
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
    except Exception:
        pass
    return await message.answer(
        f"{setter} замутил {username} {end_at_text}{f' по причине {reason}' if reason else ''}",
        reply_markup=keyboards.mute_actions(message.from_user.id, target_user_id, True),
    )


@router.message(
    Command("unmute"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
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
    Command("kick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
@router.callback_query(callbackdata.UserStats.filter(F.button == "kick"))
async def kick_command(
    message_or_query: Union[Message, CallbackQuery],
    command: Optional[CommandObject] = None,
    callback_data: Optional[callbackdata.UserStats] = None,
):
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
        member = await message_or_query.bot.get_chat_member(
            query.message.chat.id, user_id
        )
        if member.status in [
            ChatMemberStatus.KICKED,
            ChatMemberStatus.LEFT,
            ChatMemberStatus.RESTRICTED,
        ]:
            return await message_or_query.answer("Пользователь уже исключен.")
        username = member.user.username
        reason = None

    try:
        target = await message_or_query.bot.get_chat_member(message.chat.id, user_id)
        bot_member = await message_or_query.bot.get_chat_member(
            message.chat.id, message_or_query.bot.id
        )

        if target.status in ("creator", "administrator"):
            return await message_or_query.answer("Невозможно кикнуть администратора.")

        if (
            bot_member.status not in ("creator", "administrator")
            or not hasattr(bot_member, "can_restrict_members")
            or not bot_member.can_restrict_members  # type: ignore
        ):
            return await message_or_query.answer(
                "У бота нет прав на кик пользователей."
            )

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

        await message_or_query.bot.ban_chat_member(message.chat.id, user_id)
        await message_or_query.bot.unban_chat_member(message.chat.id, user_id)

        await managers.nicks.remove_nick(user_id, message.chat.id)
        await managers.user_roles.remove_role(user_id, message.chat.id)
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
    RoleFilter(enums.Role.moderator),
)
@router.callback_query(callbackdata.UserStats.filter(F.button == "ban"))
async def ban_command(
    message_or_query: Union[Message, CallbackQuery],
    command: Optional[CommandObject] = None,
    callback_data: Optional[callbackdata.UserStats] = None,
):
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
            member = await message_or_query.bot.get_chat_member(
                query.message.chat.id, target_user_id
            )
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
            await managers.nicks.remove_nick(target_user_id, message.chat.id)
            await managers.user_roles.remove_role(target_user_id, message.chat.id)
        except Exception:
            pass
        try:
            await message.bot.ban_chat_member(message.chat.id, target_user_id)
            await message.bot.unban_chat_member(message.chat.id, target_user_id)
        except Exception:
            pass

        username = await get_user_display(
            target_user_id, message_or_query.bot, message.chat.id
        )
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
    RoleFilter(enums.Role.moderator),
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
        try:
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
        except Exception:
            pass
        return await message.answer(
            f"{setter_name} разбанил пользователя {username} в этом чате."
        )
    except Exception:
        loguru.logger.exception("admin.unban handler exception:")
        return await message.answer("Неизвестная ошибка.")


@router.message(
    Command("gkick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
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
            except Exception:
                pass
            else:
                try:
                    target_role = (
                        await managers.user_roles.get(
                            managers.user_roles.make_cache_key(user_id, tg_chat_id),
                            "level",
                        )
                        or enums.Role.user
                    )
                except Exception:
                    target_role = enums.Role.user

                if target_role >= initiator_role:
                    continue

                try:
                    await message.bot.ban_chat_member(tg_chat_id, user_id)
                    if await message.bot.unban_chat_member(tg_chat_id, user_id):
                        kicked.append(tg_chat_id)
                    await managers.nicks.remove_nick(user_id, tg_chat_id)
                    await managers.user_roles.remove_role(user_id, tg_chat_id)
                except Exception:
                    pass

        kicked_titles = []
        for tg_chat_id in kicked:
            try:
                kicked_titles.append((await message.bot.get_chat(tg_chat_id)).title)
            except TelegramForbiddenError:
                pass
        kicked = "\n".join(
            [f"{k}. {i}" for k, i in enumerate(kicked_titles[:25], start=1) if i]
        )
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
