"""
Centralized app configuration.

Everything is loaded from environment variables / the .env file so that
Dev 1 (FastAPI foundation) and Dev 2 (DB foundation) share a single
source of truth instead of hardcoding values in multiple places.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- App ---
    APP_NAME: str = "Agni AI Backend"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # --- CORS ---
    CORS_ORIGINS: str = "http://localhost:3000"

    # --- Database ---
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "agni_ai_dev"

    # Optional full override; if not set, it's built from the pieces above.
    DATABASE_URL: str | None = None

        # --- Authentication / JWT ---
    JWT_SECRET_KEY: str = "change-this-secret-key"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    # --- Voice pipeline (Day 2 / Day 3) ---
    # Provider switches. "mock" is used until real vendor keys/SDKs are wired in.
    STT_PROVIDER: str = "mock"
    LLM_PROVIDER: str = "mock"
    TTS_PROVIDER: str = "mock"

    # Placeholders for future real-provider wiring — safe to leave blank for now.
    STT_API_KEY: str | None = None
    LLM_API_KEY: str | None = None
    TTS_API_KEY: str | None = None

    # How long (seconds) an idle voice session may live before it's considered expired.
    SESSION_TIMEOUT_SECONDS: int = 600
    # How many prior turns to feed back into the LLM as conversation memory.
    MAX_CONVERSATION_HISTORY: int = 20
    # Max accepted size for a single uploaded audio chunk (bytes) — basic request validation.
    MAX_AUDIO_BYTES: int = 10 * 1024 * 1024  # 10 MB

    # --- Logging ---
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is only parsed once per process."""
    return Settings()


settings = get_settings()
