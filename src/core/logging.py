import logging
import sys

from aiogram.dispatcher.event.bases import CancelHandler
from loguru import logger


class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


class SuppressCancelHandler(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info:
            exc_type, *_ = record.exc_info
            if exc_type is CancelHandler:
                return False
        return True


def setup_logger(logfile: str | None = "logs/bot.log", level: str = "DEBUG"):
    logger.remove()

    logger.add(
        sys.stdout,
        level=level.upper(),
    )

    if logfile:
        logger.add(logfile, rotation="1 day", compression="gz", level="INFO")

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    logging.getLogger().handlers = [InterceptHandler()]
    logging.getLogger().setLevel(logging.DEBUG)

    logging.getLogger("aiogram.event").addFilter(SuppressCancelHandler())

    logger.debug("Logger successfully initialized")
