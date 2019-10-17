# TGI Lecture slides

import logging
import pathlib
import re
import zipfile

import bs4
import requests

from .organizer import Organizer
from .utils import rename, stream_to_path, PrettyLogger

__all__ = ["TGI"]
logger = logging.getLogger(__name__)
pretty = PrettyLogger(logger)

class TGI:
    CRAWL_URL = "https://i11www.iti.kit.edu/teaching/{year}/tgi/index"
    BASE_URL = "https://i11www.iti.kit.edu"

    def __init__(self, base_path, year="winter2019"):
        self.base_path = base_path

        self._session = requests.Session()
        self.year = year

    def synchronize(self, to_dir, transform=lambda x: x):
        pretty.starting_synchronizer(to_dir, "TGI")

        sync_path = pathlib.Path(self.base_path, to_dir)
        orga = Organizer(self.base_path, sync_path)

        orga.clean_temp_dir()

        files = self._crawl()
        self._download(orga, files, transform)

        orga.clean_sync_dir()
        orga.clean_temp_dir()

    def _crawl(self):
        url = self.CRAWL_URL.replace("{year}", self.year)
        r = self._session.get(url)

        text = r.text
        soup = bs4.BeautifulSoup(text, "html.parser")

        files = []

        for found in soup.select("a.mediafile.mf_pdf"):
            url = found["href"]
            full_url = self.BASE_URL + url

            filename = re.search(r"\d+(/tgi)?/(.+.pdf)", url).group(2)
            path = pathlib.PurePath(filename)

            logger.debug(f"Found file {filename} at {full_url}")
            files.append((path, full_url))

        return files

    def _download(self, orga, files, transform):
        for path, url in sorted(files):
            logger.debug(f"Downloading {path}")

            new_path = transform(path)
            if new_path is not None:
                temp_file = orga.temp_file()
                self._download_file(url, temp_file)
                orga.add_file(temp_file, new_path)

    def _download_file(self, url, to_path):
        with self._session.get(url, stream=True) as r:
            stream_to_path(r, to_path)
