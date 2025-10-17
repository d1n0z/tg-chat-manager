from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject

from src.bot.filters import RoleFilter
from src.bot.keyboards import callbackdata, keyboards
from src.bot.types import CallbackQuery, Message
from src.core import enums, managers
from src.core.utils import get_user_display

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
        results.append(
            f"[{k}]. Ник: {nick_str} | {username}"
        )

    return len(nick_list_data), results, page, total_pages


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
            "Использование: /clear [количество(1-100)] или ответом на сообщение."
        )
        return

    try:
        if not command.args.isdigit() or (count := int(command.args)) not in range(
            1, 101
        ):
            await message.answer("Количество должно быть целым числом от 1 до 100.")
            return

        message_ids = [message.message_id - i for i in range(count + 1)]
        await message.bot.delete_messages(message.chat.id, message_ids)
    except Exception:
        await message.answer("Ошибка при удалении сообщений.")


@router.message(
    Command("gbynick"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def get_by_nick(message: Message, command: CommandObject):
    if not command.args:
        await message.answer("Использование: /gbynick [ник].")
        return

    nick = command.args.strip()
    nick_records = await managers.nicks.get_by_nick(message.chat.id, nick)
    if not nick_records:
        await message.answer(f"Пользователи с ником '{nick}' не найдены.")
        return

    results = []
    for nick_str, tg_user_id in nick_records[:10]:
        username = await get_user_display(tg_user_id, message.bot, message.chat.id)
        results.append(f"Ник: {nick_str} | {username}")

    await message.answer(
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
        try:
            if not managers.pyrogram_client.is_connected:
                await managers.pyrogram_client.start()
            user = await managers.pyrogram_client.get_users(username)
            if isinstance(user, list):
                user = user[0]
            target_user_id = user.id
        except Exception:
            await message.answer(f"Пользователь @{username} не найден.")
            return
    else:
        await message.answer(
            "Использование: /gnick @username или ответом на сообщение."
        )
        return

    nick = await managers.nicks.get(
        managers.nicks.make_cache_key(target_user_id, message.chat.id), "nick"
    )
    username = await get_user_display(target_user_id, message.bot, message.chat.id)
    if not nick:
        await message.answer(f"У пользователя {username} нет ника в этом чате.")
        return

    await message.answer(f"Ник пользователя {username}: <code>{nick}</code>.")


@router.message(
    Command("nlist"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    RoleFilter(enums.Role.moderator),
)
async def nick_list(message: Message, command: CommandObject):
    nicks = await managers.nicks.get_chat_nicks(message.chat.id)
    if not nicks:
        await message.answer("В этом чате нет пользователей с никами.")
        return

    total, results, page, total_pages = await _prepare_nick_list(
        message.chat.id, 0, message.bot, message.chat.id
    )

    await message.answer(
        f"Список пользователей с никами ({total}):\n\n" + "\n".join(results),
        reply_markup=keyboards.nick_list_paginate(page, total_pages, message.chat.id),
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
            page, total_pages, callback_data.chat_id
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
        await message.answer("В этом чате нет пользователей с ролями.")
        return

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

    await message.answer(text)
