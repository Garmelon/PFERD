"""
A few utility bobs and bits.
"""

import re
from pathlib import Path, PurePath
from typing import Optional, Tuple, Union

import bs4
import httpx

from .progress import ProgressSettings, progress_for, size_from_headers

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


def soupify(response: httpx.Response) -> bs4.BeautifulSoup:
    """
    Wrap a httpx response in a bs4 object.
    """

    return bs4.BeautifulSoup(response.text, "html.parser")


def stream_to_path(
        response: httpx.Response,
        target: Path,
        progress_name: Optional[str] = None,
) -> None:
    """
    Download a httpx response content to a file by streaming it. This
    function avoids excessive memory usage when downloading large files.

    If progress_name is None, no progress bar will be shown. Otherwise a progress
    bar will appear, if the download is bigger than an internal threshold.
    """

    length = size_from_headers(response)
    if progress_name and length and int(length) > 1024 * 1024 * 10:  # 10 MiB
        settings: Optional[ProgressSettings] = ProgressSettings(progress_name, length)
    else:
        settings = None

    with open(target, 'wb') as file_descriptor:
        with progress_for(settings) as progress:
            for chunk in response.iter_bytes():
                file_descriptor.write(chunk)
                progress.advance(len(chunk))


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
