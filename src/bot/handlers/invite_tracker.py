from aiogram import Router
from aiogram.types import ChatMemberUpdated

from src.core import managers

router = Router()


@router.chat_member()
async def track_invite_usage(event: ChatMemberUpdated):
    if not event.invite_link or not event.invite_link.invite_link:
        return

    if event.old_chat_member.status in [
        "left",
        "kicked",
    ] and event.new_chat_member.status not in ["left", "kicked"]:
        token = event.invite_link.invite_link.split("+")[-1]
        await managers.invite_links.increment_usage(token)
