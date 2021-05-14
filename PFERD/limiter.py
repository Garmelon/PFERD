import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncContextManager, AsyncIterator, Optional


@dataclass
class Slot:
    active: bool = False
    last_left: Optional[float] = None


class SlotPool:
    def __init__(self, limit: int, delay: float):
        if limit <= 0:
            raise ValueError("limit must be greater than 0")

        self._slots = [Slot() for _ in range(limit)]
        self._delay = delay

        self._free = asyncio.Condition()

    def _acquire_slot(self) -> Optional[Slot]:
        for slot in self._slots:
            if not slot.active:
                slot.active = True
                return slot

        return None

    def _release_slot(self, slot: Slot) -> None:
        slot.last_left = time.time()
        slot.active = False

    @asynccontextmanager
    async def limit(self) -> AsyncIterator[None]:
        slot: Slot
        async with self._free:
            while True:
                if found_slot := self._acquire_slot():
                    slot = found_slot
                    break
                await self._free.wait()

        if slot.last_left is not None:
            delay = slot.last_left + self._delay - time.time()
            if delay > 0:
                await asyncio.sleep(delay)

        try:
            yield
        finally:
            async with self._free:
                self._release_slot(slot)
                self._free.notify()


class Limiter:
    def __init__(self, crawl_limit: int, download_limit: int, delay: float):
        self._crawl_pool = SlotPool(crawl_limit, delay)
        self._download_pool = SlotPool(download_limit, delay)

    def limit_crawl(self) -> AsyncContextManager[None]:
        return self._crawl_pool.limit()

    def limit_download(self) -> AsyncContextManager[None]:
        return self._crawl_pool.limit()
