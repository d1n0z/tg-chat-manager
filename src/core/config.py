from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogsSettings(BaseSettings):
    chat_id: int
    chat_activate_thread_id: int
    access_levels_thread_id: int
    punishments_thread_id: int
    invites_thread_id: int
    general_thread_id: int


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__", extra="allow")

    logs: LogsSettings

    TOKEN: str
    API_ID: int
    API_HASH: str
    DATABASE_URL: str
    OWNER_TELEGRAM_IDS: List[int]
    ADMIN_TELEGRAM_IDS: List[int]


settings = Settings()  # type: ignore

database_config = {
    "connections": {"default": settings.DATABASE_URL},
    "apps": {
        "models": {
            "models": ["src.core.models", "aerich.models"],
            "default_connection": "default",
        },
    },
}
