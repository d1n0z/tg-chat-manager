import secrets
from datetime import datetime, timedelta, timezone
from typing import Union

import loguru
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart

from src.bot.keyboards import callbackdata, keyboards
from src.bot.types import AiogramCallbackQuery, CallbackQuery, Message
from src.core import enums, managers


async def answer_to(
    message_or_callback_querry: Union[Message, CallbackQuery], **kwargs
):
    if isinstance(message_or_callback_querry, AiogramCallbackQuery):
        await message_or_callback_querry.message.edit_text(**kwargs)
    else:
        await message_or_callback_querry.answer(**kwargs)


router = Router()


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
@router.callback_query(F.data == "start")
async def start(message_or_callback_querry: Union[Message, CallbackQuery]):
    await answer_to(
        message_or_callback_querry,
        text="Добро пожаловать.",
        reply_markup=keyboards.start(),
    )


@router.message(Command("help"), F.chat.type == ChatType.PRIVATE)
@router.callback_query(F.data == "command_help")
async def help(message_or_callback_querry: Union[Message, CallbackQuery]):
    await answer_to(
        message_or_callback_querry,
        text="""Пользователь: /id, /virus.\n
Модератор: /clear, /gbynick, /gnick, /nlist, /staff.\n
Старший модератор: /mute, /unmute, /pin, /unpin, /setrole, /removerole, /snick, /rnick.\n
Администратор: /kick, /gkick, /gban, /gunban, /unban, /words, /news, /cluster, /setwelcome, /getwelcome, /resetwelcome.""",
        reply_markup=keyboards.help(),
    )


@router.callback_query(F.data == "all_chats")
@router.callback_query(callbackdata.ChatsPaginate.filter())
async def all_chats(
    query: CallbackQuery, callback_data: callbackdata.ChatsPaginate | None = None
):
    tg_chat_ids = await managers.user_roles.get_user_chats(
        query.from_user.id, enums.Role.moderator
    )
    chat_names = [
        (tg_cid, await managers.chats.get(tg_cid, "title") or f"Chat {tg_cid}")
        for tg_cid in tg_chat_ids
    ]

    page = callback_data.page if callback_data else 0
    per_page = 10
    total_pages = (len(chat_names) - 1) // per_page if chat_names else 0
    page_chats = chat_names[page * per_page : (page + 1) * per_page]

    await query.message.edit_text(
        text="Выберите чат:",
        reply_markup=keyboards.chats_paginate(page_chats, page, total_pages),
    )


@router.callback_query(callbackdata.ChatSelect.filter())
async def chat_selected(query: CallbackQuery, callback_data: callbackdata.ChatSelect):
    tg_chat_id = int(callback_data.chat_id)
    title = await managers.chats.get(tg_chat_id, "title")

    existing_invites = await managers.invite_links.get_chat_invites(tg_chat_id)
    invite_url = None
    for invite in existing_invites:
        if (
            invite.creator_tg_id == query.from_user.id
            and invite.is_active
            and invite.used_count < invite.max_uses
        ):
            if not invite.expires_at or invite.expires_at > datetime.now(timezone.utc):
                invite_url = f"https://t.me/+{invite.token}"
                break

    text = f"Информация о чате\n\nНазвание: {title}\nID: {tg_chat_id}"
    if invite_url:
        text += f"\n\nПригласительная ссылка: {invite_url}\nДействует 1 час, на 1 вступление"

    await query.message.edit_text(
        text=text,
        reply_markup=keyboards.chat_card(tg_chat_id, invite_url),
    )


@router.callback_query(callbackdata.GenerateInvite.filter())
async def generate_invite(query: CallbackQuery, callback_data: callbackdata.GenerateInvite):
    tg_chat_id = int(callback_data.chat_id)

    bot = query.bot
    if not bot:
        return
    try:
        title = await managers.chats.get(tg_chat_id, "title")

        existing_invites = await managers.invite_links.get_chat_invites(tg_chat_id)
        for invite in existing_invites:
            if invite.creator_tg_id == query.from_user.id:
                await managers.invite_links.remove_invite(invite.token)

        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        temp_name = secrets.token_urlsafe(8)

        invite_link = await bot.create_chat_invite_link(
            tg_chat_id,
            name=f"Invite_{temp_name}",
            expire_date=expires_at,
            member_limit=1,
        )

        token = invite_link.invite_link.split("+")[-1]

        await managers.invite_links.add_invite(
            token=token,
            tg_chat_id=tg_chat_id,
            creator_tg_id=query.from_user.id,
            max_uses=1,
            expires_at=expires_at,
            single_use=True,
        )

        invite_url = invite_link.invite_link
        text = f"""Информация о чате\n
Название: {title}
ID: {tg_chat_id}\n
Пригласительная ссылка: {invite_url}
Действует 1 час, на 1 вступление"""

        await query.message.edit_text(
            text=text,
            reply_markup=keyboards.chat_card(tg_chat_id, invite_url),
        )
    except Exception as e:
        if "message is not modified" in str(e):
            return
        loguru.logger.exception("start.generate_invite handler exception:")
        try:
            await query.answer(f"Ошибка: {e}", show_alert=True)
        except TelegramBadRequest as e:
            if "MESSAGE_TOO_LONG" == str(e).split()[-1]:
                pass
            raise
