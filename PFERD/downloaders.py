"""
General downloaders useful in many situations
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from .organizer import Organizer
from .tmp_dir import TmpDir
from .transform import Transformable
from .utils import stream_to_path


@dataclass
class HttpDownloadInfo(Transformable):
    """
    This class describes a single file to be downloaded.
    """

    url: str
    parameters: Dict[str, Any] = field(default_factory=dict)


class HttpDownloader:
    """A HTTP downloader that can handle HTTP basic auth."""

    def __init__(
        self,
        tmp_dir: TmpDir,
        organizer: Organizer,
        username: Optional[str],
        password: Optional[str],
    ):
        """Create a new http downloader."""
        self._organizer = organizer
        self._tmp_dir = tmp_dir
        self._username = username
        self._password = password
        self._client = self._build_client()

    def _build_client(self) -> httpx.Client:
        if self._username and self._password:
            return httpx.Client(auth=(self._username, self._password))
        return httpx.Client()

    def download_all(self, infos: List[HttpDownloadInfo]) -> None:
        """
        Download multiple files one after the other.
        """

        for info in infos:
            self.download(info)

    def download(self, info: HttpDownloadInfo) -> None:
        """
        Download a single file.
        """

        with self._client.stream("GET", info.url, params=info.parameters) as response:
            if response.status_code == 200:
                tmp_file = self._tmp_dir.new_path()
                stream_to_path(response, tmp_file, info.path.name)
                self._organizer.accept_file(tmp_file, info.path)
            else:
                # TODO use proper exception
                raise Exception(
                    f"Could not download file, got response {response.status_code}"
                )
