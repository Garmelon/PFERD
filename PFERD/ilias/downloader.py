"""Contains a downloader for ILIAS."""

import datetime
import logging
from pathlib import Path, PurePath
from typing import Callable, List, Optional, Union

import bs4
import requests

from ..logging import PrettyLogger
from ..organizer import Organizer
from ..tmp_dir import TmpDir
from ..transform import Transformable
from ..utils import soupify, stream_to_path
from .authenticators import IliasAuthenticator

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


class ContentTypeException(Exception):
    """Thrown when the content type of the ilias element can not be handled."""


class IliasDownloadInfo(Transformable):
    """
    This class describes a single file to be downloaded.
    """

    def __init__(
            self,
            path: PurePath,
            url: Union[str, Callable[[], Optional[str]]],
            modifcation_date: Optional[datetime.datetime]
    ):
        super().__init__(path)
        if isinstance(url, str):
            string_url = url
            self.url: Callable[[], Optional[str]] = lambda: string_url
        else:
            self.url = url
        self.modification_date = modifcation_date


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

        LOGGER.debug("Downloading %r", info)
        if not self._strategy(self._organizer, info):
            self._organizer.mark(info.path)
            return

        tmp_file = self._tmp_dir.new_path()

        while not self._try_download(info, tmp_file):
            LOGGER.info("Retrying download: %r", info)
            self._authenticator.authenticate(self._session)

        self._organizer.accept_file(tmp_file, info.path)

    def _try_download(self, info: IliasDownloadInfo, target: Path) -> bool:
        url = info.url()
        if url is None:
            PRETTY.warning(f"Could not download {str(info.path)!r} as I got no URL :/")
            return True

        with self._session.get(url, stream=True) as response:
            content_type = response.headers["content-type"]

            if content_type.startswith("text/html"):
                if self._is_logged_in(soupify(response)):
                    raise ContentTypeException("Attempting to download a web page, not a file")

                return False

            # Yay, we got the file :)
            stream_to_path(response, target, info.path.name)
            return True

    @staticmethod
    def _is_logged_in(soup: bs4.BeautifulSoup) -> bool:
        userlog = soup.find("li", {"id": "userlog"})
        return userlog is not None
