from datetime import datetime, timezone

from aiogram import Router
from aiogram.enums import ChatMemberStatus
from aiogram.types import ChatMemberUpdated

from src.bot.keyboards import callbackdata, keyboards
from src.bot.types import CallbackQuery
from src.bot.utils import get_user_display
from src.core import managers
from src.core.config import settings

router = Router()


@router.chat_member()
async def track_invite_usage(event: ChatMemberUpdated):
    if not event.new_chat_member.user.is_bot:
        user = await managers.users.ensure_user(event.new_chat_member.user.id)
        if event.bot and user.banned_until and user.banned_until > datetime.now(timezone.utc):
            await event.bot.ban_chat_member(event.chat.id, event.new_chat_member.user.id)
            return await event.bot.unban_chat_member(event.chat.id, event.new_chat_member.user.id)
    if event.old_chat_member.status in [
        "left",
        "kicked",
    ] and event.new_chat_member.status not in ["left", "kicked"]:
        global_cluster = await managers.clusters.repo.get_global()
        if event.bot and (welcome := await managers.welcome_messages.get(global_cluster.id)):
            await event.bot.send_message(
                event.chat.id,
                welcome.text,
            )
        if event.invite_link and event.invite_link.invite_link:
            token = event.invite_link.invite_link.split("+")[-1]
            await managers.invite_links.increment_usage(token)


@router.my_chat_member()
async def bot_added_to_chat(event: ChatMemberUpdated):
    if (
        event.new_chat_member.status in ["member", "administrator"]
        and event.old_chat_member.status in ["left", "kicked"]
        and event.bot
    ):
        await event.bot.send_message(
            event.chat.id,
            'Для активации бота в этом чате пользователю с правами "Администратора" необходимо нажать кнопку ниже.',
            reply_markup=keyboards.activate(-1),
        )


@router.callback_query(callbackdata.Activate.filter())
async def activate(query: CallbackQuery):
    global_cluster = await managers.clusters.repo.get_global()
    await managers.chats.edit(query.message.chat.id, cluster_id=global_cluster.id)
    await managers.clusters.add_chat(global_cluster.id, query.message.chat.id)
    if not await managers.user_roles.chat_activation(
        query.from_user.id, query.message.chat.id
    ):
        return await query.answer("🔴 У вас нет прав.", show_alert=True)
    
    invite_link = await query.bot.create_chat_invite_link(
        query.message.chat.id,
        name="Invite_Infinite",
    )
    await managers.chats.edit(
        query.message.chat.id,
        infinite_invite_link=invite_link.invite_link,
    )

    username = await get_user_display(
        query.from_user.id, query.bot, query.message.chat.id, need_a_tag=True
    )
    owner = [
        i
        for i in await query.bot.get_chat_administrators(query.message.chat.id)
        if i.status == ChatMemberStatus.CREATOR
    ][0]
    ownername = await get_user_display(
        owner.user.id, query.bot, query.message.chat.id, owner, need_a_tag=True
    )
    await query.bot.send_message(
        chat_id=settings.logs.chat_id,
        message_thread_id=settings.logs.chat_activate_thread_id,
        text=f"""➡️ Активирован чат — {username}
➡️ Название: {(await query.bot.get_chat(query.message.chat.id)).title}
ℹ️ Дата: {datetime.now().strftime("%Y.%m.%d %H:%M:%S")}
ℹ️ Количество участников: {await query.bot.get_chat_member_count(query.message.chat.id)}
ℹ️ Владелец: {ownername}""",
        reply_markup=keyboards.join(0, invite_link.invite_link),
    )
    await query.message.edit_text(
        text=f"Чат {query.message.chat.id} был успешно активирован администратором - {username}."
    )
