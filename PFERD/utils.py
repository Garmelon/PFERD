"""
A few utility bobs and bits.
"""

import re
from pathlib import Path, PurePath
from typing import Optional, Tuple, Union

import bs4
import requests

PathLike = Union[PurePath, str, Tuple[str, ...]]


def to_path(pathlike: PathLike) -> Path:
    """
    Convert a given PathLike into a Path.
    """
    if isinstance(pathlike, tuple):
        return Path(*pathlike)
    return Path(pathlike)


Regex = Union[str, re.Pattern]


def to_pattern(regex: Regex) -> re.Pattern:
    """
    Convert a regex to a re.Pattern.
    """
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
