import asyncio
from contextlib import asynccontextmanager
# TODO If we upgrade to python 3.9, this context manager hint is deprecated
from typing import AsyncContextManager, AsyncIterator


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

    def limit(self) -> AsyncContextManager[None]:
        return self._context_manager()
