from aiogram.filters import BaseFilter, Command as AiogramCommand
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.core import enums, managers


class RoleFilter(BaseFilter):
    def __init__(self, min_level: enums.Role, check_is_owner: bool = False):
        self.min_level = min_level
        self.check_is_owner = check_is_owner

    async def __call__(self, message: Message) -> bool:
        print(message.chat.id)
        print(message.chat)
        print(message.sender_chat)
        if not message.from_user or not message.chat:
            return False
        user_level = await managers.user_roles.get(managers.user_roles.make_cache_key(message.from_user.id, message.chat.id), "level")
        if user_level and user_level >= self.min_level:
            return True
        if self.check_is_owner:
            return await managers.users.is_owner(message.from_user.id)
        return False


class IsOwnerFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not message.from_user:
            return False
        return await managers.users.is_owner(message.from_user.id)


class Command(AiogramCommand):
    pass


class CommandInStateFilter(BaseFilter):
    def __init__(self, value: str):
        self.value = value

    async def __call__(self, state: FSMContext) -> bool:
        data = await state.get_data()
        return data.get("command") == self.value
