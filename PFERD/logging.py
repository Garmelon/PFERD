"""
Contains a few logger utility functions and implementations.
"""

import logging
from typing import Optional

import colorama
from colorama import Fore, Style

from .utils import PathLike, to_path

STYLE = "{"
FORMAT = "[{levelname:<7}] {message}"
DATE_FORMAT = "%F %T"

FORMATTER = logging.Formatter(
    fmt=FORMAT,
    datefmt=DATE_FORMAT,
    style=STYLE,
)


def enable_logging(name: str = "PFERD", level: int = logging.INFO) -> None:
    """
    Enable and configure logging via the logging module.
    """

    handler = logging.StreamHandler()
    handler.setFormatter(FORMATTER)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    # This should be logged by our own handler, and not the root logger's
    # default handler, so we don't pass it on to the root logger.
    logger.propagate = False

    colorama.init()


class FatalException(Exception):
    """
    A fatal exception occurred. Recovery is not possible.
    """


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
        self.logger.error(
            f"{Fore.RED}{Style.BRIGHT}{message}{Style.RESET_ALL}"
        )

    def warning(self, message: str) -> None:
        """
        Print a warning message indicating some operation failed, but the error can be recovered
        or ignored.
        """
        self.logger.warning(
            f"{Fore.YELLOW}{Style.BRIGHT}{message}{Style.RESET_ALL}"
        )

    def modified_file(self, path: PathLike) -> None:
        """
        An existing file has changed.
        """

        self.logger.info(
            f"{Fore.MAGENTA}{Style.BRIGHT}Modified {self._format_path(path)}.{Style.RESET_ALL}"
        )

    def new_file(self, path: PathLike) -> None:
        """
        A new file has been downloaded.
        """

        self.logger.info(
            f"{Fore.GREEN}{Style.BRIGHT}Created {self._format_path(path)}.{Style.RESET_ALL}"
        )

    def ignored_file(self, path: PathLike, reason: str) -> None:
        """
        File was not downloaded or modified.
        """

        self.logger.info(
            f"{Style.DIM}Ignored {self._format_path(path)} "
            f"({Style.NORMAL}{reason}{Style.DIM}).{Style.RESET_ALL}"
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
            f"{Style.DIM}Not searching {self._format_path(path)} "
            f"({Style.NORMAL}{reason}{Style.DIM}).{Style.RESET_ALL}"
        )

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
        self.logger.info((
            f"{Fore.CYAN}{Style.BRIGHT}Synchronizing "
            f"{subject_str}to {self._format_path(target_directory)} "
            f"using the {synchronizer_name} synchronizer.{Style.RESET_ALL}"
        ))
