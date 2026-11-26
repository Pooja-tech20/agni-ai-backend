
"""
Centralized app configuration.

Everything is loaded from environment variables / the .env file so that
Dev 1 (FastAPI foundation) and Dev 2 (DB foundation) share a single
source of truth instead of hardcoding values in multiple places.
"""
from functools import lru_cache
from typing import List
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- App ---
    APP_NAME: str = "Agni AI Backend"
    APP_ENV: str = "development"
    DEBUG: bool = True

    # --- CORS ---
    CORS_ORIGINS: str = (
    "http://localhost:3000,"
    "http://127.0.0.1:3000,"
    "http://localhost:5173,"
    "http://127.0.0.1:5173"
)

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
    # How long a user stays logged in without typing the password again
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

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

    # --- Realtime voice pipeline (LiveKit / Deepgram / OpenAI / ElevenLabs) ---
    # The voice modules read most provider keys straight from the environment
    # (loaded from .env.local); only the Deepgram key is consumed via settings.
    DEEPGRAM_API_KEY: str | None = None

    # --- Telephony (inbound + outbound calling) ---
    TELEPHONY_PROVIDER: str = "mock"
    EXOTEL_ACCOUNT_SID: str | None = None
    EXOTEL_API_KEY: str | None = None
    EXOTEL_API_TOKEN: str | None = None
    EXOTEL_SUBDOMAIN: str = "api.exotel.com"
    EXOTEL_WEBHOOK_BASE_URL: str | None = None

    # Shared secret the provider must send to /inbound/webhook and
    # /telephony/exotel/status (header X-Webhook-Secret or ?token=).
    # REQUIRED outside development; empty means "not enforced" in dev only.
    INBOUND_WEBHOOK_SECRET: str | None = None
    # Exotel Voice flow / applet URL that bridges the answered call into
    # LiveKit SIP. Configured in the Exotel dashboard - see docs.
    EXOTEL_FLOW_URL: str | None = None

    # --- Security ---
    # Fernet key for encrypting third-party credentials stored in the DB
    # (Cal.com / GoHighLevel keys). Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    SECRETS_ENCRYPTION_KEY: str | None = None
    # Shared secret for server-to-server calls made by the voice agent
    # (appointment booking etc.). Sent as X-Agent-Secret.
    AGENT_INTERNAL_SECRET: str | None = None
    # When set, /stt/stream requires ?token=<value>. The agent subprocess
    # reads the same env var and appends it automatically.
    STT_INTERNAL_TOKEN: str | None = None
    # Requests per minute per IP for the public /chat widget endpoint.
    CHAT_RATE_LIMIT_PER_MINUTE: int = 20

    # --- Billing ---
    # Credits charged per minute of call time (override per org on Client).
    CREDITS_PER_MINUTE: float = 1.0
    # Starting credits for a newly registered organization.
    DEFAULT_SIGNUP_CREDITS: float = 10.0
    # Block calls when an organization's balance is at or below this value.
    MIN_CREDITS_TO_CALL: float = 0.0

    # --- Knowledge Base recovery ---
    RUN_KNOWLEDGE_RECOVERY: bool = False

    # --- Background workers (dialer + webhook delivery) ---
    # Run them inside the API process. For production prefer a separate
    # process: python -m app.workers.run (and set this to False on the API).
    RUN_BACKGROUND_WORKERS: bool = False
    DIALER_INTERVAL_SECONDS: int = 5
    WEBHOOK_INTERVAL_SECONDS: int = 3
    WEBHOOK_MAX_ATTEMPTS: int = 6
    WEBHOOK_TIMEOUT_SECONDS: int = 10

    # Comma-separated LLM ids offered in GET /models (the runtime default is
    # OPENAI_MODEL in .env.local).
    AVAILABLE_LLM_MODELS: str = ""

    # --- Logging ---
    LOG_LEVEL: str = "INFO"

    # .env.local holds the local voice-provider credentials.
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")

    @property
    def is_production_like(self) -> bool:
        return self.APP_ENV.lower() not in ("development", "dev", "test", "testing", "local")

    def assert_safe_for_environment(self) -> None:
        """Refuse to boot a production-like environment with insecure defaults."""
        if not self.is_production_like:
            return
        problems = []
        if self.JWT_SECRET_KEY in ("", "change-this-secret-key") or len(self.JWT_SECRET_KEY) < 32:
            problems.append("JWT_SECRET_KEY must be a random string of 32+ characters")
        if not self.INBOUND_WEBHOOK_SECRET:
            problems.append("INBOUND_WEBHOOK_SECRET must be set")
        if not self.SECRETS_ENCRYPTION_KEY:
            problems.append("SECRETS_ENCRYPTION_KEY must be set")
        if self.DEBUG:
            problems.append("DEBUG must be False")
        if problems:
            raise RuntimeError("Insecure configuration: " + "; ".join(problems))

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg2://"
            f"{quote_plus(self.POSTGRES_USER)}:"
            f"{quote_plus(self.POSTGRES_PASSWORD)}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached so the .env file is only parsed once per process."""
    return Settings()


settings = get_settings()
