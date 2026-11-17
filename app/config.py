"""Runtime configuration, read once from environment variables."""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    access_token_minutes: int
    bcrypt_rounds: int


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./resolveiq.db"),
        secret_key=os.getenv("SECRET_KEY", "dev-only-secret-change-me-in-production"),
        access_token_minutes=int(os.getenv("ACCESS_TOKEN_MINUTES", "60")),
        bcrypt_rounds=int(os.getenv("BCRYPT_ROUNDS", "12")),
    )
