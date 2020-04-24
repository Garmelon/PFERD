"""
A few utility bobs and bits.
"""

import logging
import re
from pathlib import Path, PurePath
from typing import Optional, Tuple, Union

import bs4
import requests
from colorama import Fore, Style

PathLike = Union[PurePath, str, Tuple[str, ...]]


def to_path(pathlike: PathLike) -> Path:
    if isinstance(pathlike, tuple):
        return Path(*pathlike)
    return Path(pathlike)


Regex = Union[str, re.Pattern]


def to_pattern(regex: Regex) -> re.Pattern:
    if isinstance(regex, re.Pattern):
        return regex
    return re.compile(regex)


def soupify(response: requests.Response) -> bs4.BeautifulSoup:
    """
    Wrap a requests response in a bs4 object.
    """

    return bs4.BeautifulSoup(response.text, "html.parser")


def stream_to_path(response: requests.Response, target: Path, chunk_size: int = 1024 ** 2) -> None:
    """
    Download a requests response content to a file by streaming it. This
    function avoids excessive memory usage when downloading large files. The
    chunk_size is in bytes.
    """

    with response:
        with open(target, 'wb') as file_descriptor:
            for chunk in response.iter_content(chunk_size=chunk_size):
                file_descriptor.write(chunk)


def prompt_yes_no(question: str, default: Optional[bool] = None) -> bool:
    """
    Prompts the user a yes/no question and returns their choice.
    """

    if default is True:
        prompt = "[Y/n]"
    elif default is False:
        prompt = "[y/N]"
    else:
        prompt = "[y/n]"

    text = f"{question} {prompt} "
    wrong_reply = "Please reply with 'yes'/'y' or 'no'/'n'."

    while True:
        response = input(text).strip().lower()
        if response in {"yes", "ye", "y"}:
            return True
        if response in {"no", "n"}:
            return False
        if response == "" and default is not None:
            return default
        print(wrong_reply)


class PrettyLogger:
    """
    A logger that prints some specially formatted log messages in color.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    @staticmethod
    def _format_path(path: PathLike) -> str:
        return repr(str(to_path(path)))

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
