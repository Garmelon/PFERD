import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator, Optional


@dataclass
class Slot:
    active: bool = False
    last_left: Optional[float] = None


class Limiter:
    def __init__(
            self,
            task_limit: int,
            download_limit: int,
            task_delay: float
    ):
        if task_limit <= 0:
            raise ValueError("task limit must be at least 1")
        if download_limit <= 0:
            raise ValueError("download limit must be at least 1")
        if download_limit > task_limit:
            raise ValueError("download limit can't be greater than task limit")
        if task_delay < 0:
            raise ValueError("Task delay must not be negative")

        self._slots = [Slot() for _ in range(task_limit)]
        self._downloads = download_limit
        self._delay = task_delay

        self._condition = asyncio.Condition()

    def _acquire_slot(self) -> Optional[Slot]:
        for slot in self._slots:
            if not slot.active:
                slot.active = True
                return slot

        return None

    async def _wait_for_slot_delay(self, slot: Slot) -> None:
        if slot.last_left is not None:
            delay = slot.last_left + self._delay - time.time()
            if delay > 0:
                await asyncio.sleep(delay)

    def _release_slot(self, slot: Slot) -> None:
        slot.last_left = time.time()
        slot.active = False

    @asynccontextmanager
    async def limit_crawl(self) -> AsyncIterator[None]:
        slot: Slot
        async with self._condition:
            while True:
                if found_slot := self._acquire_slot():
                    slot = found_slot
                    break
                await self._condition.wait()

        await self._wait_for_slot_delay(slot)

        try:
            yield
        finally:
            async with self._condition:
                self._release_slot(slot)
                self._condition.notify_all()

    @asynccontextmanager
    async def limit_download(self) -> AsyncIterator[None]:
        slot: Slot
        async with self._condition:
            while True:
                if self._downloads <= 0:
                    await self._condition.wait()
                    continue

                if found_slot := self._acquire_slot():
                    slot = found_slot
                    self._downloads -= 1
                    break

                await self._condition.wait()

        await self._wait_for_slot_delay(slot)

        try:
            yield
        finally:
            async with self._condition:
                self._release_slot(slot)
                self._downloads += 1
                self._condition.notify_all()
