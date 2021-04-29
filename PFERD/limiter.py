import asyncio
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import AsyncIterator


class Limiter:
    def __init__(self, limit: int = 10):
        self._semaphore = asyncio.Semaphore(limit)

    @asynccontextmanager
    async def _context_manager(self) -> AsyncIterator[None]:
        await self._semaphore.acquire()
        try:
            yield
        finally:
            self._semaphore.release()

    def limit(self) -> AbstractAsyncContextManager[None]:
        return self._context_manager()
