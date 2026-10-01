"""
Centralized logging setup.

Call `setup_logging()` once at app startup (done in app/main.py). Everywhere
else, get a module-level logger via `get_logger(__name__)`.

Every log line is automatically tagged with the current request's ID (via
contextvars), so logs from a single voice session/request can be grepped
together even across services (STT -> memory -> LLM -> TTS).
"""
import logging
import sys
from contextvars import ContextVar

from app.core.config import settings

# Populated per-request by RequestIDMiddleware; defaults to "-" outside a request.
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="-")
# Populated whenever code is operating within a voice session, for the same reason.
session_id_ctx_var: ContextVar[str] = ContextVar("session_id", default="-")


class ContextFilter(logging.Filter):
    """Injects request_id / session_id from contextvars into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx_var.get()
        record.session_id = session_id_ctx_var.get()
        return True


_LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | req=%(request_id)s | session=%(session_id)s "
    "| %(name)s | %(message)s"
)

_configured = False


def setup_logging() -> None:
    """Idempotent — safe to call multiple times (e.g. in tests)."""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.addFilter(ContextFilter())

    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL)
    root.handlers = [handler]

    # Quiet down noisy third-party loggers a little.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
