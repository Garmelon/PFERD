"""
Utility functions and a scraper/downloader for the IPD pages.
"""
import datetime
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urljoin

import bs4
import httpx

from PFERD.errors import FatalException
from PFERD.utils import soupify

from .logging import PrettyLogger
from .organizer import Organizer
from .tmp_dir import TmpDir
from .transform import Transformable
from .utils import stream_to_path

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


@dataclass
class IpdDownloadInfo(Transformable):
    """
    Information about an ipd entry.
    """

    url: str
    modification_date: Optional[datetime.datetime]


IpdDownloadStrategy = Callable[[Organizer, IpdDownloadInfo], bool]


def ipd_download_new_or_modified(organizer: Organizer, info: IpdDownloadInfo) -> bool:
    """
    Accepts new files or files with a more recent modification date.
    """
    resolved_file = organizer.resolve(info.path)
    if not resolved_file.exists():
        return True
    if not info.modification_date:
        PRETTY.ignored_file(
            info.path, "could not find modification time, file exists")
        return False

    resolved_mod_time_seconds = resolved_file.stat().st_mtime

    # Download if the info is newer
    if info.modification_date.timestamp() > resolved_mod_time_seconds:
        return True

    PRETTY.ignored_file(
        info.path, "local file has newer or equal modification time")
    return False


class IpdCrawler:
    # pylint: disable=too-few-public-methods
    """
    A crawler for IPD pages.
    """

    def __init__(self, base_url: str):
        self._base_url = base_url

    def _abs_url_from_link(self, link_tag: bs4.Tag) -> str:
        """
        Create an absolute url from an <a> tag.
        """
        return urljoin(self._base_url, link_tag.get("href"))

    def crawl(self) -> List[IpdDownloadInfo]:
        """
        Crawls the playlist given in the constructor.
        """
        page = soupify(httpx.get(self._base_url))

        items: List[IpdDownloadInfo] = []

        def is_relevant_url(x: str) -> bool:
            return (
                x.endswith(".pdf")
                or x.endswith(".c")
                or x.endswith(".java")
                or x.endswith(".zip")
            )

        for link in page.findAll(
            name="a", attrs={"href": lambda x: x and is_relevant_url(x)}
        ):
            href: str = link.attrs.get("href")
            name = href.split("/")[-1]

            modification_date: Optional[datetime.datetime] = None
            try:
                enclosing_row: bs4.Tag = link.findParent(name="tr")
                if enclosing_row:
                    date_text = enclosing_row.find(name="td").text
                    modification_date = datetime.datetime.strptime(
                        date_text, "%d.%m.%Y"
                    )
            except ValueError:
                modification_date = None

            items.append(
                IpdDownloadInfo(
                    Path(name),
                    url=self._abs_url_from_link(link),
                    modification_date=modification_date,
                )
            )

        return items


class IpdDownloader:
    """
    A downloader for ipd files.
    """

    def __init__(
        self, tmp_dir: TmpDir, organizer: Organizer, strategy: IpdDownloadStrategy
    ):
        self._tmp_dir = tmp_dir
        self._organizer = organizer
        self._strategy = strategy
        self._client = httpx.Client()

    def download_all(self, infos: List[IpdDownloadInfo]) -> None:
        """
        Download multiple files one after the other.
        """
        for info in infos:
            self.download(info)

    def download(self, info: IpdDownloadInfo) -> None:
        """
        Download a single file.
        """
        if not self._strategy(self._organizer, info):
            self._organizer.mark(info.path)
            return

        with self._client.stream("GET", info.url) as response:
            if response.status_code == 200:
                tmp_file = self._tmp_dir.new_path()
                stream_to_path(response, tmp_file, info.path.name)
                dst_path = self._organizer.accept_file(tmp_file, info.path)

                if dst_path and info.modification_date:
                    os.utime(
                        dst_path,
                        times=(
                            math.ceil(info.modification_date.timestamp()),
                            math.ceil(info.modification_date.timestamp()),
                        ),
                    )

            elif response.status_code == 403:
                raise FatalException(
                    "Received 403. Are you not using the KIT VPN?")
            else:
                PRETTY.warning(
                    f"Could not download file, got response {response.status_code}"
                )
