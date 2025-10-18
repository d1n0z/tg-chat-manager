import asyncio
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode

from src.bot import handlers
from src.bot.middlewares import loaded_middlewares
from src.core import config


@dataclass
class BotServiceConfig:
    token: str


class BotService:
    def __init__(self, service_config: BotServiceConfig) -> None:
        self._config: BotServiceConfig = service_config
        self._bot: Optional[Bot] = None
        self._dp: Optional[Dispatcher] = None
        self._session: Optional[AiohttpSession] = None

    @property
    def bot(self) -> Bot:
        if self._bot is None:
            raise RuntimeError("Bot is not initialized. Call initialize() first.")
        return self._bot

    @property
    def dp(self) -> Dispatcher:
        if self._dp is None:
            raise RuntimeError(
                "Dispatcher is not initialized. Call initialize() first."
            )
        return self._dp

    async def initialize(self) -> None:
        if (
            hasattr(config.settings, "LOCAL_SESSION_URL")
            and config.settings.LOCAL_SESSION_URL  # type: ignore
        ):
            self._session = AiohttpSession(
                api=TelegramAPIServer.from_base(
                    config.settings.LOCAL_SESSION_URL, is_local=True  # type: ignore
                )
            )
        self._dp = Dispatcher()
        self._bot = Bot(
            token=self._config.token,
            session=self._session,
            default=DefaultBotProperties(
                parse_mode=ParseMode.HTML, link_preview_is_disabled=True
            ),
        )

        for mw in loaded_middlewares:
            self.dp.update.middleware(mw())

        self._dp.include_router(handlers.root_router)

    async def run(self) -> None:
        if self._bot is None or self._dp is None:
            await self.initialize()
        if self._bot is None or self._dp is None:
            raise RuntimeError("The bot or dispatcher failed to initialize.")
        asyncio.create_task(
            self._dp.start_polling(
                self._bot, allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"]
            )
        )
