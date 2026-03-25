"""Feed polling loop — stub, implemented in Task 9."""
import asyncio
import logging

log = logging.getLogger(__name__)


async def run_polling_loop() -> None:
    """Main polling loop. Fetches due feeds from orchestrator and processes them."""
    log.info("Polling loop started (stub — waiting for fetcher implementation)")
    while True:
        await asyncio.sleep(60)
