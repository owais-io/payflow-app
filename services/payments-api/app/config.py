from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    accounts_api_url: str
    accounts_api_timeout_seconds: float = 2.0
    redis_url: str
    redis_timeout_seconds: float = 1.0
    payments_stream: str = "payflow:payments"


@lru_cache
def get_settings() -> Settings:
    return Settings()
