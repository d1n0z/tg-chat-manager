import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode

from src.bot import handlers
from src.bot.middlewares import loaded_middlewares
from src.core import config, managers


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
                    config.settings.LOCAL_SESSION_URL,  # type: ignore
                    is_local=True,
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
        self._tasks: list[asyncio.Task] = []

    async def run(self) -> None:
        if self._bot is None or self._dp is None:
            await self.initialize()
        if self._bot is None or self._dp is None:
            raise RuntimeError("The bot or dispatcher failed to initialize.")
        if getattr(config.settings, "REACTION_MONITOR_CHAT_ID", None) and getattr(
            config.settings, "REACTION_MONITOR_TOPIC_ID", None
        ):
            task = asyncio.create_task(self._reaction_watch_loop())
            self._tasks.append(task)

        await self._dp.start_polling(
            self._bot,
            allowed_updates=[
                "message",
                "callback_query",
                "message_reaction",
                "chat_member",
                "my_chat_member",
            ],
        )

    async def _reaction_watch_loop(self) -> None:
        while True:
            try:
                now = datetime.now(timezone.utc)
                watches = await managers.reaction_watches.get_unresolved_watches()
                for watch in watches:
                    try:
                        if not watch.created_at:
                            continue
                        elapsed_days = int(
                            (now - watch.created_at).total_seconds() // (24 * 3600)
                        )
                        if elapsed_days < 1:
                            continue
                        if (watch.notified_count or 0) >= elapsed_days:
                            continue

                        bot = self._bot
                        if not bot:
                            try:
                                await self.initialize()
                                bot = self._bot
                            except Exception:
                                bot = None

                        try:
                            if bot:
                                await bot.send_message(
                                    watch.chat.tg_chat_id,
                                    f"Реакция не была поставлена. Ожидание ответа — {elapsed_days * 24} часов.",
                                    reply_to_message_id=watch.message_id,
                                    message_thread_id=watch.message_thread_id,
                                )
                            await managers.reaction_watches.touch_notified_with_count(
                                watch, elapsed_days
                            )
                        except Exception:
                            pass
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(60 * 15)
