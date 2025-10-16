from aiogram import Bot as AiogramBot
from aiogram.types import CallbackQuery as AiogramCallbackQuery, User as AiogramUser
from aiogram.types import Message as AiogramMessage


class Message(AiogramMessage):  # src.bot.middlewares.ensure_message
    bot: AiogramBot  # type: ignore
    from_user: AiogramUser  # type: ignore


class CallbackQuery(AiogramCallbackQuery):  # src.bot.middlewares.ensure_message
    message: Message  # type: ignore
