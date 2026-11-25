"""Standalone worker process:  python -m app.workers.run"""
import asyncio

from app.core.logging import setup_logging
from app.workers.runner import start_workers


async def _main() -> None:
    setup_logging()
    tasks = start_workers()
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(_main())
