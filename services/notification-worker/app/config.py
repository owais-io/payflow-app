from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # No defaults: a worker pointed at the wrong Redis, or with no consumer name,
    # should fail at startup instead of quietly reading nothing.
    redis_url: str
    consumer_name: str = Field(validation_alias="HOSTNAME", min_length=1)

    payments_stream: str = "payflow:payments"
    consumer_group: str = "notification-workers"
    redis_timeout_seconds: float = Field(default=1.0, gt=0)

    # How long one XREADGROUP waits for new events. Also the worst-case delay
    # between SIGTERM and shutdown, so keep it well under the pod's 30 s grace period.
    block_ms: int = Field(default=2_000, gt=0)
    batch_size: int = Field(default=10, gt=0)
    # Events left unacked this long by any consumer (a crashed pod) are taken over.
    claim_idle_ms: int = Field(default=60_000, ge=0)

    metrics_port: int = Field(default=9100, ge=0, le=65535)


@lru_cache
def get_settings() -> Settings:
    return Settings()
