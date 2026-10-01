"""
Cross-cutting request middleware: assigns a request ID to every HTTP call,
logs entry/exit with latency, and always stamps the response with
`X-Request-ID` so the frontend/telemetry can correlate a failure with the
exact log lines that produced it.
"""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logging import get_logger, request_id_ctx_var

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_ctx_var.set(request_id)
        start = time.perf_counter()

        logger.info("--> %s %s", request.method, request.url.path)
        try:
            response = await call_next(request)
        except Exception:
            # Let the registered exception handlers deal with the response body;
            # we just make sure this is logged with the right request id first.
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "<-- %s %s failed after %.1fms", request.method, request.url.path, duration_ms
            )
            request_id_ctx_var.reset(token)
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "<-- %s %s %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        request_id_ctx_var.reset(token)
        return response
