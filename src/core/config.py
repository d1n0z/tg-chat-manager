from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    TOKEN: str
    API_ID: int
    API_HASH: str
    DATABASE_URL: str
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
