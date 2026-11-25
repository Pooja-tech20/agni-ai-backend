"""Background loops: campaign dialer + webhook delivery."""
from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.dialer import dial_tick
from app.services.webhook_service import deliver_due

logger = logging.getLogger(__name__)


def _dial_once() -> int:
    with SessionLocal() as db:
        return dial_tick(db)


def _deliver_once() -> int:
    with SessionLocal() as db:
        return deliver_due(db)


async def _loop(name: str, fn, interval: float) -> None:
    logger.info("worker '%s' started (every %ss)", name, interval)
    while True:
        try:
            await asyncio.to_thread(fn)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("worker '%s' iteration failed", name)
        await asyncio.sleep(interval)


def start_workers() -> list[asyncio.Task]:
    return [
        asyncio.create_task(_loop("dialer", _dial_once, settings.DIALER_INTERVAL_SECONDS)),
        asyncio.create_task(_loop("webhooks", _deliver_once, settings.WEBHOOK_INTERVAL_SECONDS)),
    ]


async def stop_workers(tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
