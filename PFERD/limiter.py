import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class Limiter:
    def __init__(self, limit: int = 10):
        self._semaphore = asyncio.Semaphore(limit)

    @asynccontextmanager
    async def limit(self) -> AsyncIterator[None]:
        await self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()
