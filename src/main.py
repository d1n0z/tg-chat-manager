from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from src.core.config import database_config, settings
from src.core import logging

logging.setup_logger(level="INFO")


@asynccontextmanager
async def lifespan(_: FastAPI):
    from tortoise import Tortoise

    await Tortoise.init(database_config)
    await Tortoise.generate_schemas()

    from src.core import managers, models

    await models.init()
    await managers.initialize()

    from src.bot.services.bot import BotService, BotServiceConfig

    botservice = BotService(service_config=BotServiceConfig(token=settings.TOKEN))

    await botservice.run()

    logger.success("Bot successfully started")

    yield
    await Tortoise.close_connections()
    await botservice.bot.session.close()
    await managers.close()
    logger.warning("Bot stopped")


app = FastAPI(lifespan=lifespan)


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    main()
