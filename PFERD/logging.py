import asyncio
import sys
import traceback
from contextlib import AbstractContextManager, asynccontextmanager, contextmanager
from typing import AsyncIterator, Iterator, List, Optional

from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
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
    STATUS_WIDTH = 11

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
        self.output_status = True
        self.output_not_deleted = True
        self.output_report = True

    def _update_live(self) -> None:
        elements = []
        if self._crawl_progress.task_ids:
            elements.append(self._crawl_progress)
        if self._download_progress.task_ids:
            elements.append(self._download_progress)

        group = Group(*elements)
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

    def unlock(self) -> None:
        """
        Get rid of an exclusive output state.

        This function is meant to let PFERD print log messages after the event
        loop was forcibly stopped and if it will not be started up again. After
        this is called, it is not safe to use any functions except the logging
        functions (print, warn, ...).
        """

        self._progress_suspended = False
        for line in self._lines:
            self.print(line)

    def print(self, text: str) -> None:
        """
        Print a normal message. Allows markup.
        """

        if self._progress_suspended:
            self._lines.append(text)
        else:
            self.console.print(text)

    # TODO Print errors (and warnings?) to stderr

    def warn(self, text: str) -> None:
        """
        Print a warning message. Allows no markup.
        """

        self.print(f"[bold bright_red]Warning[/] {escape(text)}")

    def warn_contd(self, text: str) -> None:
        """
        Print further lines of a warning message. Allows no markup.
        """

        self.print(f"{escape(text)}")

    def error(self, text: str) -> None:
        """
        Print an error message. Allows no markup.
        """

        self.print(f"[bold bright_red]Error[/] [red]{escape(text)}")

    def error_contd(self, text: str) -> None:
        """
        Print further lines of an error message. Allows no markup.
        """

        self.print(f"[red]{escape(text)}")

    def unexpected_exception(self) -> None:
        """
        Call this in an "except" clause to log an unexpected exception.
        """

        t, v, tb = sys.exc_info()
        if t is None or v is None or tb is None:
            # We're not currently handling an exception, so somebody probably
            # called this function where they shouldn't.
            self.error("Something unexpected happened")
            self.error_contd("")
            for line in traceback.format_stack():
                self.error_contd(line[:-1])  # Without the newline
            self.error_contd("")
        else:
            self.error("An unexpected exception occurred")
            self.error_contd("")
            self.error_contd(traceback.format_exc())

        # Our print function doesn't take types other than strings, but the
        # underlying rich.print function does. This call is a special case
        # anyways, and we're calling it internally, so this should be fine.
        self.print(Panel.fit("""
Please copy your program output and send it to the PFERD maintainers, either
directly or as a GitHub issue: https://github.com/Garmelon/PFERD/issues/new
        """.strip()))  # type: ignore

    def explain_topic(self, text: str) -> None:
        """
        Print a top-level explain text. Allows no markup.
        """

        if self.output_explain:
            self.print(f"[yellow]{escape(text)}")

    def explain(self, text: str) -> None:
        """
        Print an indented explain text. Allows no markup.
        """

        if self.output_explain:
            self.print(f"  {escape(text)}")

    def status(self, style: str, action: str, text: str, suffix: str = "") -> None:
        """
        Print a status update while crawling. Allows markup in the "style"
        argument which will be applied to the "action" string.
        """

        if self.output_status:
            action = escape(f"{action:<{self.STATUS_WIDTH}}")
            self.print(f"{style}{action}[/] {escape(text)} {suffix}")

    def not_deleted(self, style: str, action: str, text: str, suffix: str = "") -> None:
        """
        Print a message for a local only file that wasn't
        deleted while crawling. Allows markup in the "style"
        argument which will be applied to the "action" string.
        """

        if self.output_status and self.output_not_deleted:
            action = escape(f"{action:<{self.STATUS_WIDTH}}")
            self.print(f"{style}{action}[/] {escape(text)} {suffix}")

    def report(self, text: str) -> None:
        """
        Print a report after crawling. Allows markup.
        """

        if self.output_report:
            self.print(text)

    def report_not_deleted(self, text: str) -> None:
        """
        Print a report for a local only file that wasn't deleted after crawling. Allows markup.
        """

        if self.output_report and self.output_not_deleted:
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
            style: str,
            action: str,
            text: str,
            total: Optional[float] = None,
    ) -> AbstractContextManager[ProgressBar]:
        """
        Allows markup in the "style" argument which will be applied to the
        "action" string.
        """

        action = escape(f"{action:<{self.STATUS_WIDTH}}")
        description = f"{style}{action}[/] {text}"
        return self._bar(self._crawl_progress, description, total)

    def download_bar(
            self,
            style: str,
            action: str,
            text: str,
            total: Optional[float] = None,
    ) -> AbstractContextManager[ProgressBar]:
        """
        Allows markup in the "style" argument which will be applied to the
        "action" string.
        """

        action = escape(f"{action:<{self.STATUS_WIDTH}}")
        description = f"{style}{action}[/] {text}"
        return self._bar(self._download_progress, description, total)


log = Log()
