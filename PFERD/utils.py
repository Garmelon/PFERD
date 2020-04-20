import logging
import os
import sys
from pathlib import Path, PurePath
from typing import Optional, Tuple

import requests
from colorama import Fore, Style


def move(path: PurePath, from_folders: Tuple[str], to_folders: Tuple[str]) -> Optional[PurePath]:
    l = len(from_folders)
    if path.parts[:l] == from_folders:
        return PurePath(*to_folders, *path.parts[l:])
    return None


def rename(path: PurePath, to_name: str) -> PurePath:
    return PurePath(*path.parts[:-1], to_name)


def stream_to_path(response: requests.Response, to_path: Path, chunk_size: int = 1024 ** 2) -> None:
    with open(to_path, 'wb') as fd:
        for chunk in response.iter_content(chunk_size=chunk_size):
            fd.write(chunk)


def prompt_yes_no(question: str, default: Optional[bool] = None) -> bool:
    """Prompts the user and returns their choice."""
    if default is True:
        prompt = "[Y/n]"
    elif default is False:
        prompt = "[y/N]"
    else:
        prompt = "[y/n]"

    text = f"{question} {prompt} "
    WRONG_REPLY = "Please reply with 'yes'/'y' or 'no'/'n'."

    while True:
        response = input(text).strip().lower()
        if response in {"yes", "ye", "y"}:
            return True
        elif response in {"no", "n"}:
            return False
        elif response == "":
            if default is None:
                print(WRONG_REPLY)
            else:
                return default
        else:
            print(WRONG_REPLY)


class PrettyLogger:

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def modified_file(self, file_name: Path) -> None:
        self.logger.info(
            f"{Fore.MAGENTA}{Style.BRIGHT}Modified {file_name}.{Style.RESET_ALL}")

    def new_file(self, file_name: Path) -> None:
        self.logger.info(
            f"{Fore.GREEN}{Style.BRIGHT}Created {file_name}.{Style.RESET_ALL}")

    def ignored_file(self, file_name: Path) -> None:
        self.logger.info(f"{Style.DIM}Ignored {file_name}.{Style.RESET_ALL}")

    def starting_synchronizer(self, target_directory: Path, synchronizer_name: str, subject: Optional[str] = None) -> None:
        subject_str = f"{subject} " if subject else ""
        self.logger.info("")
        self.logger.info((
            f"{Fore.CYAN}{Style.BRIGHT}Synchronizing {subject_str}to {target_directory}"
            f" using the {synchronizer_name} synchronizer.{Style.RESET_ALL}"
        ))
