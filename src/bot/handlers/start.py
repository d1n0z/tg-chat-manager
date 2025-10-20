import secrets
from datetime import datetime, timedelta, timezone
from typing import Union

import loguru
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from src.bot.filters import Command
from src.bot.keyboards import callbackdata, keyboards
from src.bot.types import AiogramCallbackQuery, CallbackQuery, Message
from src.bot.utils import get_chat_info, get_user_display
from src.core import enums, managers
from src.core.config import settings


async def answer_to(
    message_or_callback_querry: Union[Message, CallbackQuery], **kwargs
):
    if isinstance(message_or_callback_querry, AiogramCallbackQuery):
        await message_or_callback_querry.message.edit_text(**kwargs)
    else:
        return await message_or_callback_querry.answer(**kwargs)


router = Router()


@router.message(Command("start"), F.chat.type == ChatType.PRIVATE)
@router.callback_query(F.data == "start")
async def start(message_or_callback_querry: Union[Message, CallbackQuery]):
    if not len(
        await managers.user_roles.get_user_roles(
            message_or_callback_querry.from_user.id
        )
    ):
        return await answer_to(
            message_or_callback_querry, text="У вас нет доступа к этому боту."
        )
    return await answer_to(
        message_or_callback_querry,
        text="Добро пожаловать.",
        reply_markup=keyboards.start(message_or_callback_querry.from_user.id),
    )


@router.message(
    Command("help"),
    F.chat.type.in_((ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP)),
)
@router.callback_query(F.data == "command_help")
async def help(message_or_callback_querry: Union[Message, CallbackQuery]):
    await answer_to(
        message_or_callback_querry,
        text="""🤖 BR | Chat Manager — ваш помощник для управления чатами!\n
📜 <b>Команды пользователя:</b>
/id @username — Telegram ID
/staff — Список ролей
/help — Список команд

👮 <b>Модератор:</b>
/clear — Удалить сообщение
/gbynick [ник] — Найти по нику
/gnick @username — Показать ник
/kick @username — Кик
/mute @username [время] — Замутить
/unmute @username — Размутить
/snick @username [ник] — Установить ник
/rnick @username — Удалить ник
/ban @username — Заблокировать
/unban @username — Разбанить
/nlist — Список ников
/pin — Закрепить
/unpin — Открепить
/gkick @username — Глобальный кик

🛡 <b>Старший модератор:</b>
/gban @username [причина] — Глобальный бан
/gunban @username — Снять глобальный бан
/setrole — Выдать роль
/removerole — Убрать роль
/setwelcome — Настроить приветствие
/getwelcome — Показать приветствие
/resetwelcome — Сбросить приветствие

👑 <b>Администратор:</b>
/words — Фильтр слов
/news [текст] — Рассылка
/cluster [create|add|remove|list] — Управление кластерами""",
        reply_markup=keyboards.help(message_or_callback_querry.from_user.id)
        if isinstance(message_or_callback_querry, AiogramCallbackQuery)
        else None,
    )


@router.callback_query(F.data == "all_chats")
@router.callback_query(callbackdata.ChatsPaginate.filter())
async def all_chats(
    query: CallbackQuery, callback_data: callbackdata.ChatsPaginate | None = None
):
    tg_chat_ids = await managers.user_roles.get_user_chats(
        query.from_user.id, enums.Role.moderator
    )
    chat_names = []
    for tg_cid in tg_chat_ids:
        try:
            title = await managers.chats.get(tg_cid, "title") or (await query.bot.get_chat(tg_cid)).title or f"Chat {tg_cid}"
        except TelegramForbiddenError:
            pass
        chat_names.append((tg_cid, title))

    page = callback_data.page if callback_data else 0
    per_page = 10
    total_pages = (len(chat_names) - 1) // per_page if chat_names else 0
    page_chats = chat_names[page * per_page : (page + 1) * per_page]

    await query.message.edit_text(
        text=f"<b>Для вас доступно {len(chat_names)} чатов.</b>\nВыберите нужный чат:",
        reply_markup=keyboards.chats_paginate(
            query.from_user.id, page_chats, page, total_pages
        ),
    )


@router.callback_query(callbackdata.ChatSelect.filter())
async def chat_selected(query: CallbackQuery, callback_data: callbackdata.ChatSelect):
    tg_chat_id = int(callback_data.chat_id)

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

    await query.message.edit_text(
        text=await get_chat_info(query.bot, tg_chat_id, invite_url),
        reply_markup=keyboards.chat_card(
            query.from_user.id,
            tg_chat_id,
            invite_url,
            infinite_invite_url=await managers.chats.get(
                tg_chat_id, "infinite_invite_link"
            ),
        ),
    )


@router.callback_query(callbackdata.GenerateInvite.filter())
async def generate_invite(
    query: CallbackQuery, callback_data: callbackdata.GenerateInvite
):
    tg_chat_id = int(callback_data.chat_id)

    bot = query.bot
    if not bot:
        return
    try:
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
        await query.bot.send_message(
            settings.logs.chat_id,
            f"""#link
➡️ Новое приглашение от {await get_user_display(query.from_user.id, query.bot, query.message.chat.id, need_a_tag=True)}
ℹ️ Чат: {(await query.bot.get_chat(tg_chat_id)).title}
ℹ️ Ссылка: {invite_link.invite_link}
ℹ️ Дата: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}""",
            message_thread_id=settings.logs.invites_thread_id,
            reply_markup=keyboards.join(0, invite_link.invite_link),
        )

        await query.message.edit_text(
            text=await get_chat_info(query.bot, tg_chat_id, invite_link.invite_link),
            reply_markup=keyboards.chat_card(
                query.from_user.id,
                tg_chat_id,
                invite_link.invite_link,
                infinite_invite_url=await managers.chats.get(
                    tg_chat_id, "infinite_invite_link"
                ),
            ),
        )
    except Exception as e:
        if "message is not modified" in str(e):
            return
        loguru.logger.exception("start.generate_invite handler exception:")
        try:
            return await query.answer(f"Ошибка: {e}", show_alert=True)
        except TelegramBadRequest as e:
            if "MESSAGE_TOO_LONG" == str(e).split()[-1]:
                pass
            raise
