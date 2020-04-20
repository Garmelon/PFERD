"""
General downloaders useful in many situations
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import requests.auth

from .organizer import Organizer
from .tmp_dir import TmpDir
from .utils import stream_to_path


@dataclass
class HttpDownloadInfo:
    """
    This class describes a single file to be downloaded.
    """

    path: Path
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
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        if self._username and self._password:
            session.auth = requests.auth.HTTPBasicAuth(
                self._username, self._password
            )
        return session


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

        with self._session.get(info.url, params=info.parameters, stream=True) as response:
            if response.status_code == 200:
                tmp_file = self._tmp_dir.new_file()
                stream_to_path(response, tmp_file)
                self._organizer.accept_file(tmp_file, info.path)
            else:
                # TODO use proper exception
                raise Exception(f"Could not download file, got response {response.status_code}")
