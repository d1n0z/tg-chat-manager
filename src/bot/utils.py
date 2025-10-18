from typing import Optional

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.types import ResultChatMemberUnion

from src.core import managers


async def get_user_display(
    tg_user_id: int,
    bot: Bot | None = None,
    chat_id: int | None = None,
    member: ResultChatMemberUnion | None = None,
) -> str:
    username = await managers.users.get_name(tg_user_id)
    if username:
        return username
    username = await managers.users.get(tg_user_id, "username")
    if username:
        return f"@{username}"
    if (bot and chat_id) or member:
        try:
            if not member and bot and chat_id:
                member = await bot.get_chat_member(chat_id, tg_user_id)
            if member:
                if member.user.username:
                    return f"@{member.user.username}"
                if member.user.full_name:
                    return member.user.full_name
        except Exception:
            pass
    return str(tg_user_id)


async def get_chat_title(chat_id: int, bot: Bot) -> str:
    return (await bot.get_chat(chat_id)).title or f"ID_{chat_id}"


async def get_chat_info(bot: Bot, chat_id: int, invite_url):
    admins = await bot.get_chat_administrators(chat_id)
    owner = [i for i in admins if i.status == ChatMemberStatus.CREATOR][0]
    owner = await get_user_display(owner.user.id, bot, chat_id, owner)
    members = await bot.get_chat_member_count(chat_id)
    text = f"""<b>Информация о чате</b>\n
<b>Название:</b> <code>{await get_chat_title(chat_id, bot)}</code>
<b>ID:</b> <code>{chat_id}</code>
<b>Владелец:</b> {owner}
<b>Количество участников:</b> <code>{members or "Неизвестно"}</code>"""
    if invite_url:
        text += f"\n\n<b>Пригласительная ссылка:</b> <code>{invite_url}<code>\n<b>Действует 1 час на 1 вступление</b>"
    return text


async def get_user_id_by_username(username: str) -> Optional[int]:
    username = username.lstrip("@")

    user = await managers.users.get_by_username(username)
    if user:
        return user.tg_user_id

    try:
        if not managers.pyrogram_client.is_connected:
            await managers.pyrogram_client.start()
        user = await managers.pyrogram_client.get_users(username)
        if isinstance(user, list):
            user = user[0]
        return user.id
    except Exception:
        return None
