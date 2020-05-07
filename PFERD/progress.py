"""
A small progress bar implementation.
"""
import sys
from dataclasses import dataclass
from types import TracebackType
from typing import Optional, Type

import requests
from rich.console import Console, ConsoleOptions, Control, RenderResult
from rich.live_render import LiveRender
from rich.progress import (BarColumn, DownloadColumn, Progress, TaskID,
                           TextColumn, TimeRemainingColumn,
                           TransferSpeedColumn)

_progress: Progress = Progress(
    TextColumn("[bold blue]{task.fields[name]}", justify="right"),
    BarColumn(bar_width=None),
    "[progress.percentage]{task.percentage:>3.1f}%",
    "•",
    DownloadColumn(),
    "•",
    TransferSpeedColumn(),
    "•",
    TimeRemainingColumn(),
    console=Console(file=sys.stdout)
)


def size_from_headers(response: requests.Response) -> Optional[int]:
    """
    Return the size of the download based on the response headers.

    Arguments:
        response {requests.Response} -- the response

    Returns:
        Optional[int] -- the size
    """
    if "Content-Length" in response.headers:
        return int(response.headers["Content-Length"])
    return None


@dataclass
class ProgressSettings:
    """
    Settings you can pass to customize the progress bar.
    """
    name: str
    max_size: int


def progress_for(settings: Optional[ProgressSettings]) -> 'ProgressContextManager':
    """
    Returns a context manager that displays progress

    Returns:
        ProgressContextManager -- the progress manager
    """
    return ProgressContextManager(settings)


class ProgressContextManager:
    """
    A context manager used for displaying progress.
    """

    def __init__(self, settings: Optional[ProgressSettings]):
        self._settings = settings
        self._task_id: Optional[TaskID] = None

    def __enter__(self) -> 'ProgressContextManager':
        """Context manager entry function."""
        if not self._settings:
            return self

        _progress.start()
        self._task_id = _progress.add_task(
            self._settings.name,
            total=self._settings.max_size,
            name=self._settings.name
        )
        return self

    # pylint: disable=useless-return
    def __exit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc_value: Optional[BaseException],
            traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        """Context manager exit function. Removes the task."""
        if self._task_id is not None:
            _progress.remove_task(self._task_id)

        if len(_progress.task_ids) == 0:
            _progress.stop()
            _progress.refresh()

            class _OneLineUp(LiveRender):
                """
                Render a control code for moving one line upwards.
                """

                def __init__(self) -> None:
                    super().__init__("not rendered")

                def __console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
                    yield Control(f"\r\x1b[1A")

            Console(file=sys.stdout).print(_OneLineUp())

        return None

    def advance(self, amount: float) -> None:
        """
        Advances the progress bar.
        """
        if self._task_id is not None:
            _progress.advance(self._task_id, amount)
