"""
A few utility bobs and bits.
"""

import logging
from pathlib import Path, PurePath
from typing import Optional, Tuple, Union

import bs4
import requests
from colorama import Fore, Style


def move(path: PurePath, from_folders: Tuple[str], to_folders: Tuple[str]) -> Optional[PurePath]:
    """
    If the input path is located anywhere within from_folders, replace the
    from_folders with to_folders. Returns None otherwise.
    """

    length = len(from_folders)
    if path.parts[:length] == from_folders:
        return PurePath(*to_folders, *path.parts[length:])
    return None


def rename(path: PurePath, to_name: str) -> PurePath:
    """
    Set the file name of the input path to to_name.
    """

    return PurePath(*path.parts[:-1], to_name)


def soupify(response: requests.Response) -> bs4.BeautifulSoup:
    """
    Wrap a requests response in a bs4 object.
    """

    return bs4.BeautifulSoup(response.text, "html.parser")


def stream_to_path(response: requests.Response, to_path: Path, chunk_size: int = 1024 ** 2) -> None:
    """
    Download a requests response content to a file by streaming it. This
    function avoids excessive memory usage when downloading large files. The
    chunk_size is in bytes.
    """

    with response:
        with open(to_path, 'wb') as file_descriptor:
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

    def modified_file(self, path: PurePath) -> None:
        """
        An existing file has changed.
        """

        self.logger.info(
            f"{Fore.MAGENTA}{Style.BRIGHT}Modified {str(path)!r}.{Style.RESET_ALL}"
        )

    def new_file(self, path: PurePath) -> None:
        """
        A new file has been downloaded.
        """

        self.logger.info(
            f"{Fore.GREEN}{Style.BRIGHT}Created {str(path)!r}.{Style.RESET_ALL}"
        )

    def ignored_file(self, path: PurePath, reason: str) -> None:
        """
        File was not downloaded or modified.
        """

        self.logger.info(
            f"{Style.DIM}Ignored {str(path)!r} "
            f"({Style.NORMAL}{reason}{Style.DIM}).{Style.RESET_ALL}"
        )

    def searching(self, path: PurePath) -> None:
        """
        A crawler searches a particular object.
        """

        self.logger.info(f"Searching {str(path)!r}")

    def not_searching(self, path: PurePath, reason: str) -> None:
        """
        A crawler does not search a particular object.
        """

        self.logger.info(
            f"{Style.DIM}Not searching {str(path)!r} "
            f"({Style.NORMAL}{reason}{Style.DIM}).{Style.RESET_ALL}"
        )

    def starting_synchronizer(
            self,
            target_directory: Union[Path, str],
            synchronizer_name: str,
            subject: Optional[str] = None,
    ) -> None:
        """
        A special message marking that a synchronizer has been started.
        """

        subject_str = f"{subject} " if subject else ""
        self.logger.info("")
        self.logger.info((
            f"{Fore.CYAN}{Style.BRIGHT}Synchronizing {subject_str}to {str(target_directory)!r}"
            f" using the {synchronizer_name} synchronizer.{Style.RESET_ALL}"
        ))
