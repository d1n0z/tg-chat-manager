from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandObject

from src.bot.filters import Command, RoleFilter
from src.bot.keyboards import callbackdata, keyboards
from src.bot.types import CallbackQuery, Message
from src.bot.utils import get_user_display, get_user_id_by_username
from src.core import enums, managers

router = Router()


async def _prepare_nick_list(chat_id: int, page: int, bot, bot_chat_id: int):
    nicks = await managers.nicks.get_chat_nicks(chat_id)
    nick_list_data = []
    for nick_obj in nicks:
        user_name = await managers.users.get_name(nick_obj.tg_user_id)
        nick_list_data.append((nick_obj.nick, user_name or str(nick_obj.tg_user_id)))

    per_page = 25
    total_pages = (len(nick_list_data) - 1) // per_page if nick_list_data else 0
    page_nicks = nick_list_data[page * per_page : (page + 1) * per_page]

    results = []
    for k, (nick_str, tg_user_id) in enumerate(page_nicks, start=(page * per_page) + 1):
        username = await get_user_display(tg_user_id, bot, bot_chat_id)
        results.append(f"[{k}]. Ник: {nick_str} | {username}")

    return len(nick_list_data), results, page, total_pages


@router.message(
    Command("clear"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def clear_messages(message: Message, command: CommandObject):
    message_ids = []
    if message.reply_to_message and not message.reply_to_message.is_topic_message:
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

    results = []
    for nick_str, tg_user_id in nick_records[:10]:
        username = await get_user_display(tg_user_id, message.bot, message.chat.id)
        results.append(f"Ник: {nick_str} | {username}")

    return await message.answer(
        f"Найдено: {len(nick_records)}\n\n"
        + "\n".join([f"[{k}]. {i}" for k, i in enumerate(results, start=1)])
    )


@router.message(
    Command("gnick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def get_nick(message: Message, command: CommandObject):
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
    elif command.args:
        username = command.args.lstrip("@")
        target_user_id = await get_user_id_by_username(username)
        if not target_user_id:
            return
    else:
        return await message.answer(
            "Использование: /gnick @username или ответом на сообщение."
        )

    nick = await managers.nicks.get(
        managers.nicks.make_cache_key(target_user_id, message.chat.id), "nick"
    )
    username = await get_user_display(target_user_id, message.bot, message.chat.id)
    if not nick:
        return

    return await message.answer(f"Ник пользователя {username}: <code>{nick}</code>.")


@router.message(
    Command("nlist"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def nick_list(message: Message, command: CommandObject):
    nicks = await managers.nicks.get_chat_nicks(message.chat.id)
    if not nicks:
        return await message.answer("В этом чате нет пользователей с никами.")

    total, results, page, total_pages = await _prepare_nick_list(
        message.chat.id, 0, message.bot, message.chat.id
    )

    return await message.answer(
        f"Список пользователей с никами ({total}):\n\n" + "\n".join(results),
        reply_markup=keyboards.nick_list_paginate(
            message.from_user.id, page, total_pages, message.chat.id
        ),
    )


@router.callback_query(callbackdata.NickListPaginate.filter())
async def nick_list_page(
    query: CallbackQuery, callback_data: callbackdata.NickListPaginate
):
    total, results, page, total_pages = await _prepare_nick_list(
        callback_data.chat_id, callback_data.page, query.bot, query.message.chat.id
    )

    await query.message.edit_text(
        f"Список пользователей с никами ({total}):\n\n" + "\n".join(results),
        reply_markup=keyboards.nick_list_paginate(
            query.from_user.id, page, total_pages, callback_data.chat_id
        ),
    )


@router.message(
    Command("staff"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def staff_list(message: Message, command: CommandObject):
    roles = await managers.user_roles.get_chat_roles(message.chat.id)
    if not roles:
        return await message.answer("В этом чате нет пользователей с ролями.")

    by_role = {}
    for role in roles:
        if role.level not in by_role:
            by_role[role.level] = []
        by_role[role.level].append(role.tg_user_id)

    text = "Список администрации:\n\n"
    for level in sorted(by_role.keys(), key=lambda x: x.level, reverse=True):
        text += f"<b>{level.value.title()}:</b>\n"
        for tg_user_id in by_role[level]:
            username = await get_user_display(tg_user_id, message.bot, message.chat.id)
            text += f"  • {username}\n"
        text += "\n"

    return await message.answer(text)
