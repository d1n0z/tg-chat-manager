from src.bot.middlewares.callback_initiator import CallbackInitiatorMiddleware
from src.bot.middlewares.delete_command import DeleteCommandMiddleware
from src.bot.middlewares.ensure_message import EnsureMessageMiddleware
from src.bot.middlewares.message_logger import MessageLoggerMiddleware
from src.bot.middlewares.word_filter import WordFilterMiddleware

loaded_middlewares = [
    MessageLoggerMiddleware,
    EnsureMessageMiddleware,
    CallbackInitiatorMiddleware,
    WordFilterMiddleware,
    DeleteCommandMiddleware,
]
