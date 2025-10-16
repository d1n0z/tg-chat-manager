from aiogram.filters import BaseFilter
from aiogram.types import Message

from src.core import enums, managers


class RoleFilter(BaseFilter):
    def __init__(self, min_level: enums.Role):
        self.min_level = min_level

    async def __call__(self, message: Message) -> bool:
        if not message.from_user or not message.chat:
            return False
        user_level = await managers.user_roles.get(managers.user_roles.make_cache_key(message.from_user.id, message.chat.id), "level")
        return user_level and user_level >= self.min_level


class IsOwnerFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not message.from_user:
            return False
        return await managers.users.is_owner(message.from_user.id)
