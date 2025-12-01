import asyncio

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject

from src.bot.filters import IsOwnerFilter
from src.bot.types import Message
from src.core.config import settings
from src.core.enums import Role
from src.core.managers import chats, user_roles, users

router = Router()


@router.message(Command("add"), F.chat.type == ChatType.PRIVATE, IsOwnerFilter())
async def add(message: Message, command: CommandObject):
    if not command.args:
        return await message.answer("Использование: /add [tg_user_id: int]")

    try:
        uid = int(command.args.strip())
    except ValueError:
        return await message.answer("tg_user_id должен быть числом")
    msg = await message.answer("Добавляю роли пользователю...")

    env_path = ".env"
    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    updated = False
    for i, line in enumerate(lines):
        if line.startswith("ADMIN_TELEGRAM_IDS="):
            current = line.split("=", 1)[1].strip()
            current = current.strip("[]")
            ids = [int(x.strip()) for x in current.split(",") if x.strip()]

            if uid not in ids:
                ids.append(uid)
                lines[i] = f"ADMIN_TELEGRAM_IDS=[{', '.join(map(str, ids))}]\n"
                updated = True
            break

    if updated:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        settings.ADMIN_TELEGRAM_IDS.append(uid)

    await users.ensure_user(uid)
    all_chats = await chats.get_all_chats()

    added_count = 0
    for chat in all_chats:
        try:
            await asyncio.wait_for(
                message.bot.get_chat_member(chat.tg_chat_id, uid), timeout=3.0
            )
            await user_roles.add_role(uid, chat.tg_chat_id, Role.admin)
            added_count += 1
        except Exception:
            continue
        await asyncio.sleep(0.1)

    await msg.edit_text(
        f"Пользователь {uid} добавлен как администратор\nРоль назначена в {added_count} из {len(all_chats)} чатов"
    )
    return msg
