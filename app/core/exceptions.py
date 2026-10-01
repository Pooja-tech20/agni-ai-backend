"""
Structured error handling.

Every error the API returns — whether raised deliberately (AppError
subclasses) or an unexpected bug — comes back in the same JSON shape:

{
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "Human-readable explanation",
    "details": { ...optional structured context... }
  },
  "request_id": "abc123"
}

This makes the voice-agent frontend's error handling trivial: switch on
`error.code`, not on brittle status-text string matching.
"""
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, request_id_ctx_var

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for every deliberate, structured application error."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "APP_ERROR"

    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


# --- Session errors -----------------------------------------------------
class SessionNotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "SESSION_NOT_FOUND"


class SessionExpiredError(AppError):
    status_code = status.HTTP_410_GONE
    code = "SESSION_EXPIRED"


class SessionAlreadyEndedError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "SESSION_ALREADY_ENDED"


# --- Request validation (beyond what Pydantic covers) --------------------
class InvalidAudioError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "INVALID_AUDIO"


class PayloadTooLargeError(AppError):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    code = "PAYLOAD_TOO_LARGE"


# --- Pipeline stage errors ------------------------------------------------
class STTProcessingError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "STT_PROCESSING_ERROR"


class LLMProcessingError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "LLM_PROCESSING_ERROR"


class TTSProcessingError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "TTS_PROCESSING_ERROR"


def _error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "error": {"code": code, "message": message, "details": details or {}},
        "request_id": request_id_ctx_var.get(),
    }


def register_exception_handlers(app: FastAPI) -> None:
    """Wire every handler onto the FastAPI app. Called once from app/main.py."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        logger.warning("AppError %s on %s: %s", exc.code, request.url.path, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # Drop the raw "ctx" (can hold non-serializable exception objects from
        # custom validators) — the "msg" field already carries that context as text.
        fields = [{k: v for k, v in err.items() if k != "ctx"} for err in exc.errors()]
        logger.warning("Validation error on %s: %s", request.url.path, fields)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body(
                "VALIDATION_ERROR",
                "Request failed validation.",
                {"fields": jsonable_encoder(fields)},
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s", request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(
                "INTERNAL_ERROR", "Something went wrong processing your request."
            ),
        )
