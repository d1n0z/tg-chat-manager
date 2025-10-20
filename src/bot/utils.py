import re
from datetime import timedelta
from typing import Optional

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import ResultChatMemberUnion

from src.core import managers


async def get_user_display(
    tg_user_id: int,
    bot: Bot | None = None,
    chat_id: int | None = None,
    member: ResultChatMemberUnion | None = None,
    need_a_tag: bool = False,
    nick_if_has: bool = False,
    no_tag: bool = False
) -> str:
    if chat_id and bot:
        username = await get_username_by_user_id(tg_user_id, chat_id, bot)
        if not username:
            username = await managers.users.get(tg_user_id, "username")
    else:
        username = await managers.users.get(tg_user_id, "username")
    a_href = f"tg://user?id={tg_user_id}" if not no_tag or not username else f"t.me/{username}"
    if nick_if_has and chat_id:
        nick = await managers.nicks.get_user_nick(tg_user_id, chat_id)
        if nick:
            return f'<a href="{a_href}">{nick.nick}</a>' if need_a_tag else f"{nick.nick}"
    if username:
        if no_tag:
            return f'<a href="{a_href}">@\u200B{username}</a>'
        else:
            return f"@{username}"
    if (bot and chat_id) or member:
        try:
            if not member and bot and chat_id:
                member = await bot.get_chat_member(chat_id, tg_user_id)
            if member:
                if member.user.username:
                    if no_tag:
                        return f'<a href="{a_href}">@\u200B{member.user.username}</a>'
                    else:
                        return f"@{member.user.username}"
                if member.user.full_name:
                    return (
                        f'<a href="{a_href}">{member.user.full_name}</a>'
                        if need_a_tag
                        else member.user.full_name
                    )
        except Exception:
            pass
    return (
        f'<a href="{a_href}">ID_{tg_user_id}</a>'
        if need_a_tag
        else f"ID_{tg_user_id}"
    )


async def get_chat_title(chat_id: int, bot: Bot) -> str:
    title = f"ID_{chat_id}"
    try:
        return (await bot.get_chat(chat_id)).title or title
    except TelegramForbiddenError:
        pass
    return title


async def get_chat_info(bot: Bot, chat_id: int, invite_url):
    admins = await bot.get_chat_administrators(chat_id)
    tg_owner = [i for i in admins if i.status == ChatMemberStatus.CREATOR][0]
    owner = await get_user_display(tg_owner.user.id, bot, chat_id, tg_owner)
    members = await bot.get_chat_member_count(chat_id)
    text = f"""<b>Информация о чате</b>\n
<b>Название:</b> <code>{await get_chat_title(chat_id, bot)}</code>
<b>ID:</b> <code>{chat_id}</code>
<b>Владелец:</b> {owner if owner.startswith("@") else f'<a href="tg://user?id={tg_owner.user.id}">{owner}</a>'}
<b>Количество участников:</b> <code>{members or "Неизвестно"}</code>"""
    if invite_url:
        text += f"\n\n<b>Пригласительная ссылка:</b> <code>{invite_url}</code>\n<b>Действует 1 час на 1 вступление</b>"
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


async def get_username_by_user_id(user_id: int, chat_id: int, bot: Bot) -> Optional[str]:
    try:
        user = (await bot.get_chat_member(chat_id, user_id)).user
        return user.username
    except Exception:
        return
    


def parse_duration(duration_str: str) -> timedelta | None:
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
