import warnings

from aiogram import Bot as AiogramBot
from aiogram.types import CallbackQuery as AiogramCallbackQuery, User as AiogramUser
from aiogram.types import Message as AiogramMessage


with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message='Field name ".*" in "Message" shadows an attribute')

    class Message(AiogramMessage):  # src.bot.middlewares.ensure_message
        bot: AiogramBot  # type: ignore
        from_user: AiogramUser  # type: ignore


with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message='Field name ".*" in "CallbackQuery" shadows an attribute')

    class CallbackQuery(AiogramCallbackQuery):  # src.bot.middlewares.ensure_message
        message: Message  # type: ignore
        bot: AiogramBot  # type: ignore
