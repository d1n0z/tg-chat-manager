from src.core import managers


async def get_user_display(tg_user_id: int, bot=None, chat_id: int | None = None) -> str:
    username = await managers.users.get_name(tg_user_id)
    if username:
        return username
    username = await managers.users.get(tg_user_id, "username")
    if username:
        return f"@{username}"
    if bot and chat_id:
        try:
            member = await bot.get_chat_member(chat_id, tg_user_id)
            if member.user.username:
                return f"@{member.user.username}"
            if member.user.first_name:
                return member.user.first_name
        except Exception:
            pass
    return str(tg_user_id)
