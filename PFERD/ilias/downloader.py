"""Contains a downloader for ILIAS."""

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import bs4
import requests

from ..organizer import Organizer
from ..tmp_dir import TmpDir
from ..utils import soupify, stream_to_path
from .authenticators import IliasAuthenticator


class ContentTypeException(Exception):
    """Thrown when the content type of the ilias element can not be handled."""


@dataclass
class IliasDownloadInfo:
    """
    This class describes a single file to be downloaded.
    """

    path: Path
    url: str
    modification_date: datetime.datetime
    # parameters: Dict[str, Any] = field(default_factory=dict)


class IliasDownloader:
    """A downloader for ILIAS."""

    def __init__(self, tmp_dir: TmpDir, organizer: Organizer, authenticator: IliasAuthenticator):
        """Create a new IliasDownloader."""
        self._authenticator = authenticator
        self._session = requests.Session()
        self._tmp_dir = tmp_dir
        self._organizer = organizer

    def download_all(self, infos: List[IliasDownloadInfo]) -> None:
        """
        Download multiple files one after the other.
        """

        for info in infos:
            self.download(info)

    def download(self, info: IliasDownloadInfo) -> None:
        """
        Download a file from ILIAS.

        Retries authentication until eternity if it could not fetch the file.
        """

        tmp_file = self._tmp_dir.new_file()

        while not self._try_download(info, tmp_file):
            self._authenticator.authenticate(self._session)

        self._organizer.accept_file(tmp_file, info.path)

    def _try_download(self, info: IliasDownloadInfo, target: Path) -> bool:
        with self._session.get(info.url, stream=True) as response:
            content_type = response.headers["content-type"]

            if content_type.startswith("text/html"):
                # Dangit, we're probably not logged in.
                if self._is_logged_in(soupify(response)):
                    raise ContentTypeException("Attempting to download a web page, not a file")

                return False

            # Yay, we got the file :)
            stream_to_path(response, target)
            return True

    @staticmethod
    def _is_logged_in(soup: bs4.BeautifulSoup) -> bool:
        userlog = soup.find("li", {"id": "userlog"})
        return userlog is not None
