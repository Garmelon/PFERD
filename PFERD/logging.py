import asyncio
import sys
import traceback
from contextlib import asynccontextmanager, contextmanager
# TODO In Python 3.9 and above, ContextManager and AsyncContextManager are deprecated
from typing import AsyncIterator, ContextManager, Iterator, List, Optional

from rich.console import Console, RenderGroup
from rich.live import Live
from rich.markup import escape
from rich.progress import (BarColumn, DownloadColumn, Progress, TaskID, TextColumn, TimeRemainingColumn,
                           TransferSpeedColumn)
from rich.table import Column


class ProgressBar:
    def __init__(self, progress: Progress, taskid: TaskID):
        self._progress = progress
        self._taskid = taskid

    def advance(self, amount: float = 1) -> None:
        self._progress.advance(self._taskid, advance=amount)

    def set_total(self, total: float) -> None:
        self._progress.update(self._taskid, total=total)
        self._progress.start_task(self._taskid)


class Log:
    def __init__(self) -> None:
        self.console = Console(highlight=False)

        self._crawl_progress = Progress(
            TextColumn("{task.description}", table_column=Column(ratio=1)),
            BarColumn(),
            TimeRemainingColumn(),
            expand=True,
        )
        self._download_progress = Progress(
            TextColumn("{task.description}", table_column=Column(ratio=1)),
            TransferSpeedColumn(),
            DownloadColumn(),
            BarColumn(),
            TimeRemainingColumn(),
            expand=True,
        )

        self._live = Live(console=self.console, transient=True)
        self._update_live()

        self._showing_progress = False
        self._progress_suspended = False
        self._lock = asyncio.Lock()
        self._lines: List[str] = []

        # Whether different parts of the output are enabled or disabled
        self.output_explain = False
        self.output_action = True
        self.output_report = True

    def _update_live(self) -> None:
        elements = []
        if self._crawl_progress.task_ids:
            elements.append(self._crawl_progress)
        if self._download_progress.task_ids:
            elements.append(self._download_progress)

        group = RenderGroup(*elements)  # type: ignore
        self._live.update(group)

    @contextmanager
    def show_progress(self) -> Iterator[None]:
        if self._showing_progress:
            raise RuntimeError("Calling 'show_progress' while already showing progress")

        self._showing_progress = True
        try:
            with self._live:
                yield
        finally:
            self._showing_progress = False

    @asynccontextmanager
    async def exclusive_output(self) -> AsyncIterator[None]:
        if not self._showing_progress:
            raise RuntimeError("Calling 'exclusive_output' while not showing progress")

        async with self._lock:
            self._progress_suspended = True
            self._live.stop()
            try:
                yield
            finally:
                self._live.start()
                self._progress_suspended = False
                for line in self._lines:
                    self.print(line)
                self._lines = []

    def print(self, text: str) -> None:
        if self._progress_suspended:
            self._lines.append(text)
        else:
            self.console.print(text)

    def warn(self, text: str) -> None:
        self.print(f"[bold bright_red]Warning[/] {escape(text)}")

    def error(self, text: str) -> None:
        self.print(f"[bold bright_red]Error[/] [red]{escape(text)}")

    def error_contd(self, text: str) -> None:
        self.print(f"[red]{escape(text)}")

    def unexpected_exception(self) -> None:
        t, v, tb = sys.exc_info()

        self.error("An unexpected exception occurred")
        self.error_contd("")

        for line in traceback.format_tb(tb):
            self.error_contd(line[:-1])  # Without trailing newline

        if str(v):
            self.error_contd(f"{t.__name__}: {v}")
        else:
            self.error_contd(t.__name__)

        self.error_contd("")
        self.error_contd("""
An unexpected exception occurred. This usually shouldn't happen. Please copy
your program output and send it to the PFERD maintainers, either directly or as
a GitHub issue: https://github.com/Garmelon/PFERD/issues/new
        """.strip())

    def explain_topic(self, text: str) -> None:
        if self.output_explain:
            self.print(f"[cyan]{escape(text)}")

    def explain(self, text: str) -> None:
        if self.output_explain:
            self.print(f"  {escape(text)}")

    def action(self, text: str) -> None:
        if self.output_action:
            self.print(text)

    def report(self, text: str) -> None:
        if self.output_report:
            self.print(text)

    @contextmanager
    def _bar(
            self,
            progress: Progress,
            description: str,
            total: Optional[float],
    ) -> Iterator[ProgressBar]:
        if total is None:
            # Indeterminate progress bar
            taskid = progress.add_task(description, start=False)
        else:
            taskid = progress.add_task(description, total=total)
        self._update_live()

        try:
            yield ProgressBar(progress, taskid)
        finally:
            progress.remove_task(taskid)
            self._update_live()

    def crawl_bar(
            self,
            description: str,
            total: Optional[float] = None,
    ) -> ContextManager[ProgressBar]:
        return self._bar(self._crawl_progress, description, total)

    def download_bar(
            self,
            description: str,
            total: Optional[float] = None,
    ) -> ContextManager[ProgressBar]:
        return self._bar(self._download_progress, description, total)


log = Log()
