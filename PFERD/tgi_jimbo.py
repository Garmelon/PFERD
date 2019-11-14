# TGI Tutorial slides

import logging
import pathlib
import re
import zipfile

import bs4
import requests

from .organizer import Organizer
from .utils import rename, stream_to_path, PrettyLogger

__all__ = ["TGI_Tut"]
logger = logging.getLogger(__name__)
pretty = PrettyLogger(logger)


class TGI_Tut:
    CRAWL_URL = "https://tgitut.jimdo.com"

    def __init__(self, base_path, year="winter2019"):
        self.base_path = base_path

        self._session = requests.Session()

    def _login(self):
        post = self._session.post(self.CRAWL_URL, data={
            "password": "Lebkuchen", "do_login": "yes", "Submit": "Anmelden"
        })

    def synchronize(self, to_dir, transform=lambda x: x):
        pretty.starting_synchronizer(to_dir, "TGI_Tut")

        self._login()

        sync_path = pathlib.Path(self.base_path, to_dir)
        orga = Organizer(self.base_path, sync_path)

        orga.clean_temp_dir()

        files = self._crawl()
        self._download(orga, files, transform)

        orga.clean_sync_dir()
        orga.clean_temp_dir()

    def _crawl(self):
        url = self.CRAWL_URL
        r = self._session.get(url)

        text = r.text
        soup = bs4.BeautifulSoup(text, "html.parser")
        files = []

        for found in soup.select("a.cc-m-download-link"):
            url = found["href"]
            full_url = self.CRAWL_URL + url

            filename = re.search(r"/app/download/\d+/(.*.pdf)", url).group(1)
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
