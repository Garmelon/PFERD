import asyncio
from contextlib import asynccontextmanager, contextmanager
from types import TracebackType
from typing import AsyncIterator, Iterator, List, Optional, Type

from rich.console import Console
from rich.progress import Progress, TaskID


class ProgressBar:
    def __init__(self, progress: Progress, taskid: TaskID):
        self._progress = progress
        self._taskid = taskid

    def advance(self, amount: float = 1) -> None:
        self._progress.advance(self._taskid, advance=amount)

    def set_total(self, total: float) -> None:
        self._progress.update(self._taskid, total=total)


class TerminalConductor:
    def __init__(self) -> None:
        self._stopped = False
        self._lock = asyncio.Lock()
        self._lines: List[str] = []

        self._console = Console(highlight=False)
        self._progress = Progress(console=self._console)

    async def _start(self) -> None:
        for task in self._progress.tasks:
            task.visible = True
        self._progress.start()

        self._stopped = False

        for line in self._lines:
            self.print(line)
        self._lines = []

    async def _stop(self) -> None:
        self._stopped = True

        for task in self._progress.tasks:
            task.visible = False
        self._progress.stop()

    async def __aenter__(self) -> None:
        async with self._lock:
            await self._start()

    async def __aexit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc_value: Optional[BaseException],
            traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        async with self._lock:
            await self._stop()
        return None

    def print(self, line: str) -> None:
        if self._stopped:
            self._lines.append(line)
        else:
            self._console.print(line)

    @asynccontextmanager
    async def exclusive_output(self) -> AsyncIterator[None]:
        async with self._lock:
            await self._stop()
            try:
                yield
            finally:
                await self._start()

    @contextmanager
    def progress_bar(
            self,
            description: str,
            total: Optional[float] = None,
    ) -> Iterator[ProgressBar]:
        if total is None:
            # Indeterminate progress bar
            taskid = self._progress.add_task(description, start=False)
        else:
            taskid = self._progress.add_task(description, total=total)

        bar = ProgressBar(self._progress, taskid)
        try:
            yield bar
        finally:
            self._progress.remove_task(taskid)
