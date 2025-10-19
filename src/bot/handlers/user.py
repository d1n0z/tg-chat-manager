from datetime import datetime

import loguru
from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from pyrogram.errors import UsernameNotOccupied

from src.bot.handlers.moderator import get_sort_key
from src.bot import states
from src.bot.keyboards import callbackdata, keyboards
from src.bot.types import CallbackQuery, Message
from src.bot.utils import get_user_display, get_user_id_by_username
from src.core import enums, managers
from src.core.config import settings

router = Router()


@router.message(Command("id"), F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}))
async def get_user_id(message: Message, command: CommandObject):
    if message.entities and len(message.entities) > 1:
        mention = message.entities[1]
        if mention.type == "text_mention" and mention.user:
            return await message.answer(
                f"ID пользователя {mention.user.first_name}: <code>{mention.user.id}</code>"
            )

    if not command.args:
        if message.from_user and message.from_user.id and message.from_user.username:
            return await message.answer(
                f"ID пользователя @{message.from_user.username}: <code>{message.from_user.id}</code>"
            )

        return await message.answer(
            "Использование: /id @username или упомяните пользователя."
        )

    username = command.args.lstrip("@")

    try:
        if not managers.pyrogram_client.is_connected:
            await managers.pyrogram_client.start()
        user = await managers.pyrogram_client.get_users(username)
        if isinstance(user, list):
            user = user[0]
        return await message.answer(
            f"ID пользователя @{username}: <code>{user.id}</code>"
        )
    except UsernameNotOccupied:
        return await message.answer(f"Пользователь @{username} не найден.")
    except Exception:
        loguru.logger.exception("user.id handler exception:")
        return await message.answer("Ошибка при получении ID.")


@router.message(
    Command("stats"), F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP})
)
async def stats(message: Message, command: CommandObject):
    try:
        if not command.args or not (
            (
                await managers.user_roles.get(
                    managers.user_roles.make_cache_key(
                        message.from_user.id, message.chat.id
                    ),
                    "level",
                )
                or enums.Role.user
            )
            >= enums.Role.senior_moderator
        ):
            username = message.from_user.username
            user_id = message.from_user.id
        else:
            username = command.args.lstrip("@")
            user_id = await get_user_id_by_username(username)
            if not user_id:
                raise ValueError
        if (await message.bot.get_chat_member(message.chat.id, user_id)).status not in [
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.MEMBER,
        ]:
            return await message.answer("Пользователь не является участником чата.")
        messages_count = await managers.users.get(user_id, "messages_count")
        nick = await managers.nicks.get_user_nick(user_id, message.chat.id)
        role = (
            await managers.user_roles.get(
                managers.user_roles.make_cache_key(user_id, message.chat.id),
                "level",
            )
            or enums.Role.user
        )
        return await message.answer(
            f"""👤 Пользователь: {await get_user_display(user_id, message.bot, message.chat.id, need_a_tag=True)}
📛 Ник: {nick.nick if nick else "Не установлен"}
💬 Сообщений: {messages_count or 0}
👑 Роль: {role.value}""",
            reply_markup=keyboards.user_stats(message.from_user.id, user_id)
            if user_id != message.from_user.id
            else None,
        )
    except UsernameNotOccupied:
        return await message.answer(f"Пользователь @{username} не найден.")
    except Exception:
        loguru.logger.exception("user.stats handler exception:")
        return await message.answer("Ошибка при получении статистики.")


@router.callback_query(callbackdata.UserStats.filter(F.button == "nick"))
async def change_nick_callback_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: callbackdata.UserStats
):
    message = await callback.message.answer("Отправьте новый ник для пользователя:")
    await state.set_state(states.UserStatsState.set_nick)
    await state.update_data(
        target_user_id=callback_data.user_id, delete_message=message
    )
    return message


@router.message(states.UserStatsState.set_nick)
async def receive_new_nick(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    target_user_id: int = data["target_user_id"]
    await data["delete_message"].delete()

    if not message.text:
        return await message.answer("Неверный никнейм.")

    await managers.nicks.add_nick(target_user_id, message.chat.id, message.text.strip())

    await message.answer(
        f'{await get_user_display(message.from_user.id, bot, message.chat.id, need_a_tag=True)} установил новый ник "{message.text.strip()}" пользователю {await get_user_display(target_user_id, bot, message.chat.id, need_a_tag=True)}.'
    )
    await state.clear()


@router.callback_query(callbackdata.UserStats.filter(F.button == "access"))
async def grant_rights_callback_handler(
    query: CallbackQuery, callback_data: callbackdata.UserStats
):
    target_user_id = int(callback_data.user_id)
    await query.message.edit_reply_markup(
        reply_markup=keyboards.user_stats(query.from_user.id, target_user_id, True)
    )


@router.callback_query(callbackdata.UserStats.filter(F.button.startswith("set_access")))
async def grant_role_choice_handler(
    query: CallbackQuery, bot: Bot, callback_data: callbackdata.UserStats
):
    if not query.message.text:
        raise Exception("AAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    target_user_id = int(callback_data.user_id)
    role = enums.Role[callback_data.access_key]  # type: ignore

    is_owner = await managers.users.is_owner(query.from_user.id)
    initiator_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(
                query.from_user.id, query.message.chat.id
            ),
            "level",
        )
        or enums.Role.user
    )
    if role >= initiator_role and not is_owner:
        return await query.answer("Нельзя выдать роль большую или равную вашей роли.")

    target_role = (
        await managers.user_roles.get(
            managers.user_roles.make_cache_key(target_user_id, query.message.chat.id),
            "level",
        )
        or enums.Role.user
    )
    if target_role >= initiator_role and not is_owner:
        return await query.answer("Нельзя выдать роль человеку, старшему по роли.")

    await managers.user_roles.add_role(
        target_user_id, query.message.chat.id, role, query.from_user.id
    )

    try:
        await bot.edit_message_text(
            chat_id=query.message.chat.id,
            message_id=query.message.message_id,
            text=query.message.text[: query.message.text.rfind(": ") + 2] + role.value,
            reply_markup=keyboards.user_stats(query.from_user.id, target_user_id),
        )
    except Exception:
        pass

    setter = await get_user_display(
        query.from_user.id, bot, query.message.chat.id, need_a_tag=True
    )
    username = await get_user_display(
        target_user_id, bot, query.message.chat.id, need_a_tag=True
    )
    invite = await managers.chats.get(query.message.chat.id, "infinite_invite_link")
    await query.bot.send_message(
        settings.logs.chat_id,
        f"""#setrole
➡️ Чат: {query.message.chat.title}\n
➡️ Пользователь: {setter}
➡️ Уровень прав: {initiator_role.value}
ℹ️ Действие: Выдал права
ℹ️ Права: {role.value}
➡️ Цель: {username}""",
        message_thread_id=settings.logs.access_levels_thread_id,
        reply_markup=keyboards.join(0, invite) if invite else None,
    )
    await query.message.answer(
        f'{setter} выдал роль "{role.value}" пользователю {username}.'
    )


@router.message(
    lambda m: (
        (m.text or "?").split()[0].lower()
        in (
            "mute",
            "unmute",
            "ban",
            "unban",
            "warn",
            "unwarn",
            "sban",
            "spermban",
            "permban",
        )
    )
)
async def forms(message: Message):
    if not message.text:
        return
    form = f"/{message.text[0].lower()}{message.text[1:]}"
    await message.answer(
        f"<code>{form}</code>\n\n📝 Форму отправил: {await get_user_display(message.from_user.id, message.bot, message.chat.id, need_a_tag=True, nick_if_has=True)} ({datetime.now().strftime('%d.%m.%Y %H:%M:%S')})",
        reply_markup=keyboards.form(-1),
    )


@router.callback_query(callbackdata.Form.filter())
async def form_accept_callback_handler(
    query: CallbackQuery, callback_data: callbackdata.Form
):
    if not query.message.text:
        return
    answer_by = await get_user_display(
        query.from_user.id,
        query.bot,
        query.message.chat.id,
        need_a_tag=True,
        nick_if_has=True,
    )
    date = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    text = (
        f"✅ Форма была принята пользователем {answer_by} ({date})"
        if callback_data.accept
        else f"❌ Форма была отклонена пользователем {answer_by} ({date})"
    )
    text += (
        "\n\n"
        + "\n<blockquote>".join(
            query.message.html_text.replace("\n\n", "\n").split("\n")[::-1]
        )
        + "</blockquote>"
    )
    await query.message.edit_text(text=text, reply_markup=None)


@router.message(
    Command("staff"),
    F.chat.type.in_({ChatType.SUPERGROUP, ChatType.GROUP}),
    # RoleFilter(enums.Role.moderator),
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
        staff = []
        for tg_user_id in by_role[level]:
            username = await get_user_display(
                tg_user_id,
                message.bot,
                message.chat.id,
                need_a_tag=True,
                nick_if_has=True,
                no_tag=True,
            )
            staff.append(f"  • {username}\n")
        for username in sorted(staff, key=get_sort_key):
            text += username
        text += "\n"

    return await message.answer(text)
