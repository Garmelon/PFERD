import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional

import requests

from .logging import FatalException, PrettyLogger
from .organizer import Organizer
from .tmp_dir import TmpDir
from .transform import Transformable
from .utils import stream_to_path

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


@dataclass
class DivaDownloadInfo(Transformable):
    """
    Information about a DIVA video
    """
    url: str


DivaDownloadStrategy = Callable[[Organizer, DivaDownloadInfo], bool]


def diva_download_new(organizer: Organizer, info: DivaDownloadInfo) -> bool:
    """
    Accepts only new files.
    """
    resolved_file = organizer.resolve(info.path)
    if not resolved_file.exists():
        return True
    PRETTY.ignored_file(info.path, "local file exists")
    return False


class DivaPlaylistCrawler:
    # pylint: disable=too-few-public-methods
    """
    A crawler for DIVA playlists.
    """

    _BASE_URL = "https://mediaservice.bibliothek.kit.edu/asset/collection.json"

    def __init__(self, playlist_id: str):
        self._id = playlist_id

    def crawl(self) -> List[DivaDownloadInfo]:
        """
        Crawls the playlist given in the constructor.
        """
        response = requests.get(self._BASE_URL, params={"collection": self._id})
        if response.status_code != 200:
            raise FatalException(f"Server returned status {response.status_code}.")

        body = response.json()

        if body["error"]:
            raise FatalException(f"Server returned error {body['error']!r}.")

        result = body["result"]

        if result["resultCount"] > result["pageSize"]:
            PRETTY.warning("Did not receive all results, some will be missing")

        download_infos: List[DivaDownloadInfo] = []

        for video in result["resultList"]:
            title = video["title"]
            collection_title = self._follow_path(["collection", "title"], video)
            url = self._follow_path(
                ["resourceList", "derivateList", "mp4", "url"],
                video
            )

            if url and collection_title and title:
                path = Path(collection_title, title + ".mp4")
                download_infos.append(DivaDownloadInfo(path, url))
            else:
                PRETTY.warning(f"Incomplete video found: {title!r} {collection_title!r} {url!r}")

        return download_infos

    @staticmethod
    def _follow_path(path: List[str], obj: Any) -> Optional[Any]:
        """
        Follows a property path through an object, bailing at the first None.
        """
        current = obj
        for path_step in path:
            if path_step in current:
                current = current[path_step]
            else:
                return None
        return current


class DivaDownloader:
    """
    A downloader for DIVA videos.
    """

    def __init__(self, tmp_dir: TmpDir, organizer: Organizer, strategy: DivaDownloadStrategy):
        self._tmp_dir = tmp_dir
        self._organizer = organizer
        self._strategy = strategy
        self._session = requests.session()

    def download_all(self, infos: List[DivaDownloadInfo]) -> None:
        """
        Download multiple files one after the other.
        """
        for info in infos:
            self.download(info)

    def download(self, info: DivaDownloadInfo) -> None:
        """
        Download a single file.
        """
        if not self._strategy(self._organizer, info):
            self._organizer.mark(info.path)
            return

        with self._session.get(info.url, stream=True) as response:
            if response.status_code == 200:
                tmp_file = self._tmp_dir.new_path()
                stream_to_path(response, tmp_file, info.path.name)
                self._organizer.accept_file(tmp_file, info.path)
            else:
                PRETTY.warning(f"Could not download file, got response {response.status_code}")
