from loguru import logger

from src.core.config import database_config, settings
from src.core import logging

logging.setup_logger(level="INFO")


async def main():
    from tortoise import Tortoise

    await Tortoise.init(database_config)
    await Tortoise.generate_schemas()

    from src.core import managers, models

    await models.init()
    await managers.initialize()

    from src.bot.services.bot import BotService, BotServiceConfig

    botservice = BotService(service_config=BotServiceConfig(token=settings.TOKEN))

    await botservice.run()

    await Tortoise.close_connections()
    await botservice.bot.session.close()
    await managers.close()

    logger.warning("Bot stopped")
