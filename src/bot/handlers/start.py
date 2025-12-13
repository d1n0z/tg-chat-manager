import asyncio
import json
import re
import secrets
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Union

import loguru
from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext

from src.bot import states
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


async def user_in_massform_chat(bot: Bot, user_id: int):
    try:
        return (
            await bot.get_chat_member(settings.MASSFORM_CHAT_ID, user_id)
        ).status in [
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.CREATOR,
            ChatMemberStatus.ADMINISTRATOR,
        ]
    except Exception:
        return False


router = Router()


@router.message(Command("start"), F.chat.type == ChatType.PRIVATE)
@router.callback_query(F.data == "start")
async def start(message_or_callback_querry: Union[Message, CallbackQuery]):
    all_chats_access = False
    if len(
        await managers.user_roles.get_user_roles(
            message_or_callback_querry.from_user.id
        )
    ):
        all_chats_access = True
    return await answer_to(
        message_or_callback_querry,
        text="Добро пожаловать.",
        reply_markup=keyboards.start(
            message_or_callback_querry.from_user.id,
            await user_in_massform_chat(
                message_or_callback_querry.bot, message_or_callback_querry.from_user.id
            ), all_chats_access
        ),
    )


@router.message(Command("start"), F.chat.type != ChatType.PRIVATE)
async def start_group(message: Message):
    await message.bot.send_message(
        message.chat.id,
        'Для активации бота в этом чате пользователю с правами "Администратора" необходимо нажать кнопку ниже.',
        reply_markup=keyboards.activate(-1),
    )


@router.message(
    Command("help"),
    F.chat.type.in_((ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP)),
)
@router.callback_query(F.data == "command_help")
async def help(message_or_callback_querry: Union[Message, CallbackQuery]):
    return await answer_to(
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


@router.callback_query(F.data == "mass_form_hint")
async def mass_form_hint(callback_query: CallbackQuery):
    return await answer_to(
        callback_query,
        text="⚙️ Отправьте пример формы в формате: /permban @ БОТ by I.ivanov\n⚙️ За место @ будут вписаны никнеймы игроков.",
        reply_markup=keyboards.help(callback_query.from_user.id)
        if isinstance(callback_query, AiogramCallbackQuery)
        else None,
    )


@router.callback_query(F.data == "ip_analytics_hint")
async def ip_analytics_hint(callback_query: CallbackQuery):
    return await answer_to(
        callback_query,
        text="⚙️ Пожалуйста, введите IP-адрес или несколько через пробел.",
        reply_markup=keyboards.help(callback_query.from_user.id)
        if isinstance(callback_query, AiogramCallbackQuery)
        else None,
    )


@router.message(
    Command(
        "mute",
        "unmute",
        "ban",
        "unban",
        "warn",
        "unwarn",
        "sban",
        "spermban",
        "permban",
    ),
    F.chat.type == ChatType.PRIVATE,
)
async def forms(message: Message, state: FSMContext):
    if (
        not await user_in_massform_chat(message.bot, message.from_user.id)
        or not message.text
    ):
        return
    form = message.text
    msg = await message.answer(
        "⚙️ Отправьте никнеймы игроков через пробел. (Ivan_Ivanov Test_Test)"
    )
    await state.set_state(states.MassForm.gather_nicks)
    await state.set_data({"form": form, "delete_message": msg})
    return msg


@router.message(states.MassForm.gather_nicks)
async def massform_gather_nicks(message: Message, state: FSMContext):
    if not message.text:
        return
    delete_message = (await state.get_data()).get("delete_message")
    if delete_message:
        await delete_message.delete()
    if (
        not await user_in_massform_chat(message.bot, message.from_user.id)
        or not message.text
    ):
        await state.clear()
        return
    nicks = message.text.split()
    form = (await state.get_data()).get("form")
    if not form:
        return await message.answer("Системная ошибка. Пожалуйста, попробуйте ещё раз.")
    text = "⚙️ <b>Созданные формы:</b>\n\n"
    for i in range(0, len(nicks), 100):
        for nick in nicks[i:i + 100]:
            text += f"<code>{form.replace('@', f'{nick}')}</code>\n"
        msg = await message.answer(text)
        text = ""
    await state.clear()
    return msg


_IPV4_RE = r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"


@router.message(F.text.regexp(_IPV4_RE))
async def ip_analytics_gather(message: Message, state: FSMContext):
    async def _fetch_ip_info_batch(ips: list[str]) -> list[dict]:
        url = "http://ip-api.com/batch?fields=status,message,country,regionName,city,isp,as,query,zip,lat,lon,proxy,hosting,org"

        data = json.dumps([{"query": ip} for ip in ips]).encode("utf-8")

        def _sync():
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.load(resp)

        try:
            return await asyncio.to_thread(_sync)
        except Exception:
            return []

    def _format_ip_info(info: dict, idx: int) -> str:
        if not info or info.get("status") != "success":
            return f"IP {idx}: {info.get('query', 'unknown')}\nОшибка получения информации\n\n"
        vpn = (
            "VPN используется"
            if info.get("proxy") or info.get("hosting")
            else "VPN не используется"
        )
        lines = [
            f"IP {idx}: {info.get('query')}",
            f"Страна: {info.get('country')}",
            f"Регион: {info.get('regionName')}",
            f"Город: {info.get('city')}",
            "VPN: " + vpn,
            "\nДополнительно:",
            f"Провайдер: {info.get('isp')}",
            f"Доп. инфа: {info.get('as') or info.get('org')}",
            f"Интернет: {'Мобильный' if 'mobile' in (info.get('org') or '').lower() else 'WiFi'}",
            (
                "VPN не используется"
                if not (info.get("proxy") or info.get("hosting"))
                else "VPN используется"
            ),
        ]
        return "\n".join(lines) + "\n\n"

    def _distance_km(a: dict, b: dict) -> float:
        from math import asin, cos, radians, sin, sqrt

        lat1, lon1 = a.get("lat"), a.get("lon")
        lat2, lon2 = b.get("lat"), b.get("lon")
        if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
            return 0.0
        lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        _a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        _c = 2 * asin(sqrt(_a))
        return 6371.0 * _c

    if not message.text:
        return
    delete_message = (await state.get_data()).get("delete_message")
    if delete_message:
        try:
            await delete_message.delete()
        except Exception:
            pass

    if not await user_in_massform_chat(message.bot, message.from_user.id):
        await state.clear()
        return

    ips = re.compile(_IPV4_RE).findall(message.text)
    if not ips:
        await state.clear()
        return await message.answer(
            "Не найдено корректных IPv4 адресов. Попробуйте ещё раз."
        )

    infos = await _fetch_ip_info_batch(ips)

    if not infos:
        await state.clear()
        return await message.answer(
            "Не удалось получить данные по IP. Попробуйте позже."
        )

    text = "⚙️ Информация о IP-адресах:\n\n"
    for idx, info in enumerate(infos, start=1):
        text += _format_ip_info(info, idx)

    if len(infos) > 1:
        text += "Расстояния:\n"
        for i, a in enumerate(infos):
            for j, b in enumerate(infos):
                if i == j:
                    continue
                dist = _distance_km(a, b)
                text += f"Расстояние между IP {a.get('query')} и {b.get('query')}: {dist:.3f} км\n"

    await message.answer(text)
    await state.clear()
    return


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
            title = (
                await managers.chats.get(tg_cid, "title")
                or (await query.bot.get_chat(tg_cid)).title
                or f"Chat {tg_cid}"
            )
        except Exception:
            pass
        else:
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
