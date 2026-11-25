"""Small in-memory sliding-window rate limiter (per client IP).

Good enough for one API process. With several instances, each keeps its own
counters - move this to Redis (or an API gateway) before scaling out.
"""
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import settings

_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # Behind a trusted proxy configure uvicorn --proxy-headers so this is the real IP.
    return request.client.host if request.client else "unknown"


def reset_rate_limits() -> None:
    _hits.clear()


def rate_limit_chat(request: Request) -> None:
    limit = settings.CHAT_RATE_LIMIT_PER_MINUTE
    if limit <= 0:
        return
    now = time.monotonic()
    bucket = _hits[_client_ip(request)]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Please slow down.")
    bucket.append(now)
