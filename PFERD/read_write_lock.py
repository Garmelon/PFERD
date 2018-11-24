# From https://charemza.name/blog/posts/python/asyncio/read-write-lock/
# https://gist.github.com/michalc/ab9bd571cfab09216c0316f2302a76b0#file-asyncio_read_write_lock-py

import asyncio
import collections
import contextlib


class _ReadWaiter(asyncio.Future):
    pass

class _WriteWaiter(asyncio.Future):
    pass

class ReadWriteLock():

    def __init__(self):
        self._waiters = collections.deque()
        self._reads_held = 0
        self._write_held = False

    def _pop_queued_waiters(self, waiter_type):
        while True:
            correct_type = self._waiters and isinstance(self._waiters[0], waiter_type)
            cancelled = self._waiters and self._waiters[0].cancelled()

            if correct_type or cancelled:
                waiter = self._waiters.popleft()

            if correct_type and not cancelled:
                yield waiter

            if not correct_type and not cancelled:
                break

    def _resolve_queued_waiters(self):
        if not self._write_held:
            for waiter in self._pop_queued_waiters(_ReadWaiter):
                self._reads_held += 1
                waiter.set_result(None)

        if not self._write_held and not self._reads_held:
            for waiter in self._pop_queued_waiters(_WriteWaiter):
                self._write_held = True
                waiter.set_result(None)
                break

    def _on_read_release(self):
        self._reads_held -= 1

    def _on_write_release(self):
        self._write_held = False

    @contextlib.asynccontextmanager
    async def _acquire(self, waiter_type, on_release):
        waiter = waiter_type()
        self._waiters.append(waiter)
        self._resolve_queued_waiters()

        try:
            await waiter
        except asyncio.CancelledError:
            self._resolve_queued_waiters()
            raise

        try:
            yield
        finally:
            on_release()
            self._resolve_queued_waiters()

    @contextlib.asynccontextmanager
    async def read(self):
        async with self._acquire(_ReadWaiter, self._on_read_release):
            yield

    @contextlib.asynccontextmanager
    async def write(self):
        async with self._acquire(_WriteWaiter, self._on_write_release):
            yield
