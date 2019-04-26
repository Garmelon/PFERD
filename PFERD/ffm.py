# Fakultät für Mathematik (FfM)

import logging
import pathlib
import re

import bs4
import requests

from .organizer import Organizer
from .utils import stream_to_path

__all__ = ["FfM"]
logger = logging.getLogger(__name__)

class FfM:
    BASE_URL = "http://www.math.kit.edu/"
    LINK_RE = re.compile(r"^https?://www.math.kit.edu/.*/(.*\.pdf)$")

    def __init__(self, base_path):
        self.base_path = base_path

        self._session = requests.Session()

    def synchronize(self, urlpart, to_dir, transform=lambda x: x):
        logger.info(f"    Synchronizing {urlpart} to {to_dir} using the FfM synchronizer.")

        sync_path = pathlib.Path(self.base_path, to_dir)

        orga = Organizer(self.base_path, sync_path)
        orga.clean_temp_dir()

        self._crawl(orga, urlpart, transform)

        orga.clean_sync_dir()
        orga.clean_temp_dir()

    def _crawl(self, orga, urlpart, transform):
        url = self.BASE_URL + urlpart
        r = self._session.get(url)
        soup = bs4.BeautifulSoup(r.text, "html.parser")

        for found in soup.find_all("a", href=self.LINK_RE):
            url = found["href"]
            filename = re.match(self.LINK_RE, url).group(1).replace("/", ".")
            logger.debug(f"Found file {filename} at {url}")

            old_path = pathlib.PurePath(filename)
            new_path = transform(old_path)
            if new_path is None:
                continue
            logger.debug(f"Transformed from {old_path} to {new_path}")

            temp_path = orga.temp_file()
            self._download(url, temp_path)
            orga.add_file(temp_path, new_path)

    def _download(self, url, to_path):
        with self._session.get(url, stream=True) as r:
            stream_to_path(r, to_path)
