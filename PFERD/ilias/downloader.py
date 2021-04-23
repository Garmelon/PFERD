"""Contains a downloader for ILIAS."""

import datetime
import logging
import math
import os
from pathlib import Path, PurePath
from typing import Callable, Awaitable, List, Optional, Union

import bs4
import httpx
import asyncio

from ..errors import retry_on_io_exception
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
            url: Union[str, Callable[[], Awaitable[Optional[str]]]],
            modifcation_date: Optional[datetime.datetime]
    ):
        super().__init__(path)
        if isinstance(url, str):
            future = asyncio.Future()
            future.set_result(url)
            self.url: Callable[[], Optional[str]] = lambda: future
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
            client: httpx.Client,
            authenticator: IliasAuthenticator,
            strategy: IliasDownloadStrategy,
            timeout: int = 5
    ):
        """
        Create a new IliasDownloader.
        """

        self._tmp_dir = tmp_dir
        self._organizer = organizer
        self._client = client
        self._authenticator = authenticator
        self._strategy = strategy
        self._timeout = timeout

    async def download_all(self, infos: List[IliasDownloadInfo]) -> None:
        """
        Download multiple files one after the other.
        """

        tasks = [self.download(info) for info in infos]
        await asyncio.gather(*tasks)

    async def download(self, info: IliasDownloadInfo) -> None:
        """
        Download a file from ILIAS.

        Retries authentication until eternity if it could not fetch the file.
        """

        LOGGER.debug("Downloading %r", info)

        if not self._strategy(self._organizer, info):
            self._organizer.mark(info.path)
            return

        tmp_file = self._tmp_dir.new_path()

        @retry_on_io_exception(3, "downloading file")
        async def download_impl() -> bool:
            if not await self._try_download(info, tmp_file):
                LOGGER.info("Re-Authenticating due to download failure: %r", info)
                self._authenticator.authenticate(self._client)
                raise IOError("Scheduled retry")
            else:
                return True

        if not await download_impl():
            PRETTY.error(f"Download of file {info.path} failed too often! Skipping it...")
            return

        dst_path = self._organizer.accept_file(tmp_file, info.path)
        if dst_path and info.modification_date:
            os.utime(
                dst_path,
                times=(
                    math.ceil(info.modification_date.timestamp()),
                    math.ceil(info.modification_date.timestamp())
                )
            )

    async def _try_download(self, info: IliasDownloadInfo, target: Path) -> bool:
        url = await info.url()
        if url is None:
            PRETTY.warning(f"Could not download {str(info.path)!r} as I got no URL :/")
            return True

        with self._client.stream("GET", url, timeout=self._timeout) as response:
            content_type = response.headers["content-type"]
            has_content_disposition = "content-disposition" in response.headers

            if content_type.startswith("text/html") and not has_content_disposition:
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
