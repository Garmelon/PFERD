"""Contains a downloader for ILIAS."""

import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import bs4
import requests

from ..organizer import Organizer
from ..tmp_dir import TmpDir
from ..transform import Transformable
from ..utils import PrettyLogger, soupify, stream_to_path
from .authenticators import IliasAuthenticator

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


class ContentTypeException(Exception):
    """Thrown when the content type of the ilias element can not be handled."""


@dataclass
class IliasDownloadInfo(Transformable):
    """
    This class describes a single file to be downloaded.
    """

    url: str
    modification_date: Optional[datetime.datetime]
    # parameters: Dict[str, Any] = field(default_factory=dict)


IliasDownloadStrategy = Callable[[Organizer, IliasDownloadInfo], bool]


def download_everything(organizer: Organizer, info: IliasDownloadInfo) -> bool:
    # pylint: disable=unused-argument
    """
    Accepts everything.
    """
    return True


def download_modified_or_new(organizer: Organizer, info: IliasDownloadInfo) -> bool:
    """
    Accepts new files or files with a more recent modification date.
    """
    resolved_file = organizer.resolve(info.path)
    if not resolved_file.exists() or info.modification_date is None:
        return True
    resolved_mod_time_seconds = resolved_file.stat().st_mtime

    # Download if the info is newer
    if info.modification_date.timestamp() > resolved_mod_time_seconds:
        return True

    PRETTY.ignored_file(info.path, "local file has newer or equal modification time")
    return False


class IliasDownloader:
    # pylint: disable=too-many-arguments
    """A downloader for ILIAS."""

    def __init__(
            self,
            tmp_dir: TmpDir,
            organizer: Organizer,
            session: requests.Session,
            authenticator: IliasAuthenticator,
            strategy: IliasDownloadStrategy,
    ):
        """
        Create a new IliasDownloader.
        """

        self._tmp_dir = tmp_dir
        self._organizer = organizer
        self._session = session
        self._authenticator = authenticator
        self._strategy = strategy

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

        if not self._strategy(self._organizer, info):
            self._organizer.mark(info.path)
            return

        tmp_file = self._tmp_dir.new_path()

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
