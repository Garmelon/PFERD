"""
Contains a few logger utility functions and implementations.
"""

import logging
from typing import Optional

from rich._log_render import LogRender
from rich.console import Console
from rich.style import Style
from rich.text import Text
from rich.theme import Theme

from .download_summary import DownloadSummary
from .utils import PathLike, to_path

STYLE = "{"
FORMAT = "[{levelname:<7}] {message}"
DATE_FORMAT = "%F %T"


def enable_logging(name: str = "PFERD", level: int = logging.INFO) -> None:
    """
    Enable and configure logging via the logging module.
    """

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(RichLoggingHandler(level=level))

    # This should be logged by our own handler, and not the root logger's
    # default handler, so we don't pass it on to the root logger.
    logger.propagate = False


class RichLoggingHandler(logging.Handler):
    """
    A logging handler that uses rich for highlighting
    """

    def __init__(self, level: int) -> None:
        super().__init__(level=level)
        self.console = Console(
            theme=Theme({"logging.level.warning": Style(color="yellow")})
        )
        self._log_render = LogRender(show_level=True, show_time=False, show_path=False)

    def emit(self, record: logging.LogRecord) -> None:
        """
        Invoked by logging.
        """
        log_style = f"logging.level.{record.levelname.lower()}"
        message = self.format(record)

        level = Text()
        level.append(record.levelname, log_style)
        message_text = Text.from_markup(message)

        self.console.print(
            self._log_render(
                self.console,
                [message_text],
                level=level,
            )
        )


class PrettyLogger:
    """
    A logger that prints some specially formatted log messages in color.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    @staticmethod
    def _format_path(path: PathLike) -> str:
        return repr(str(to_path(path)))

    def error(self, message: str) -> None:
        """
        Print an error message indicating some operation fatally failed.
        """
        self.logger.error(f"[bold red]{message}[/bold red]")

    def warning(self, message: str) -> None:
        """
        Print a warning message indicating some operation failed, but the error can be recovered
        or ignored.
        """
        self.logger.warning(f"[bold yellow]{message}[/bold yellow]")

    def modified_file(self, path: PathLike) -> None:
        """
        An existing file has changed.
        """

        self.logger.info(
            f"[bold magenta]Modified {self._format_path(path)}.[/bold magenta]"
        )

    def new_file(self, path: PathLike) -> None:
        """
        A new file has been downloaded.
        """

        self.logger.info(f"[bold green]Created {self._format_path(path)}.[/bold green]")

    def deleted_file(self, path: PathLike) -> None:
        """
        A file has been deleted.
        """

        self.logger.info(f"[bold red]Deleted {self._format_path(path)}.[/bold red]")

    def ignored_file(self, path: PathLike, reason: str) -> None:
        """
        File was not downloaded or modified.
        """

        self.logger.info(
            f"[dim]Ignored {self._format_path(path)} " f"([/dim]{reason}[dim]).[/dim]"
        )

    def searching(self, path: PathLike) -> None:
        """
        A crawler searches a particular object.
        """

        self.logger.info(f"Searching {self._format_path(path)}")

    def not_searching(self, path: PathLike, reason: str) -> None:
        """
        A crawler does not search a particular object.
        """

        self.logger.info(
            f"[dim]Not searching {self._format_path(path)} "
            f"([/dim]{reason}[dim]).[/dim]"
        )

    def summary(self, download_summary: DownloadSummary) -> None:
        """
        Prints a download summary.
        """
        self.logger.info("")
        self.logger.info("[bold cyan]Download Summary[/bold cyan]")
        if not download_summary.has_updates():
            self.logger.info("[bold dim]Nothing changed![/bold dim]")
            return

        for new_file in download_summary.new_files:
            self.new_file(new_file)
        for modified_file in download_summary.modified_files:
            self.modified_file(modified_file)
        for deleted_files in download_summary.deleted_files:
            self.deleted_file(deleted_files)

    def starting_synchronizer(
        self,
        target_directory: PathLike,
        synchronizer_name: str,
        subject: Optional[str] = None,
    ) -> None:
        """
        A special message marking that a synchronizer has been started.
        """

        subject_str = f"{subject} " if subject else ""
        self.logger.info("")
        self.logger.info(
            (
                f"[bold cyan]Synchronizing "
                f"{subject_str}to {self._format_path(target_directory)} "
                f"using the {synchronizer_name} synchronizer.[/bold cyan]"
            )
        )
