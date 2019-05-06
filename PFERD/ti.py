# Fakultät für Mathematik (FfM)

import getpass
import logging
import pathlib
import re

import bs4
import requests

from .organizer import Organizer
from .utils import stream_to_path

__all__ = ["Ti"]
logger = logging.getLogger(__name__)

class Ti:
    BASE_URL = "http://ti.ira.uka.de/"
    FILE_RE = re.compile(r"^.+\.pdf$")

    def __init__(self, base_path):
        self.base_path = base_path

        self._session = requests.Session()
        self._credentials = None

    def synchronize(self, urlpart, to_dir, transform=lambda x: x,
            filter=lambda x: True):
        logger.info(f"    Synchronizing {urlpart} to {to_dir} using the Ti synchronizer.")

        sync_path = pathlib.Path(self.base_path, to_dir)

        orga = Organizer(self.base_path, sync_path)
        orga.clean_temp_dir()

        self._reset_credentials()

        available = self._find_available(urlpart)

        if "Folien" in available:
            path = pathlib.PurePath("Folien")
            if filter(path):
                self._crawl(urlpart + available["Folien"], path, orga,
                        transform)
            else:
                logger.info("Skipping Folien/")

        if "Blätter" in available:
            path = pathlib.PurePath("Blätter")
            if filter(path):
                self._crawl(urlpart + available["Blätter"], path, orga,
                        transform)
            else:
                logger.info("Skipping Blätter/")

        orga.clean_sync_dir()
        orga.clean_temp_dir()

        self._reset_credentials()

    def _find_available(self, urlpart):
        url = self.BASE_URL + urlpart
        r = self._session.get(url)
        soup = bs4.BeautifulSoup(r.text, "html.parser")

        available = {}

        if soup.find(href="./Vorlesung/Vorlesung.php"):
            logger.info("Found Folien/")
            available["Folien"] = "/Vorlesung/"
        if soup.find(href="./Uebungen/Uebungen.php"):
            logger.info("Found Blätter/")
            available["Blätter"] = "/Uebungen/"

        return available

    def _crawl(self, urlpart, path, orga, transform):
        url = self.BASE_URL + urlpart
        r = self._session.get(url)
        soup = bs4.BeautifulSoup(r.text, "html.parser")

        for filelink in soup.find_all("a", href=self.FILE_RE):
            filepath = path / filelink["href"]
            fileurl = url + "/" + filelink["href"]

            new_path = transform(filepath)
            if new_path is None:
                continue
            logger.debug(f"Transformed from {filepath} to {new_path}")

            temp_path = orga.temp_file()
            self._download(fileurl, temp_path)
            orga.add_file(temp_path, new_path)


    def _get_credentials(self):
        if self._credentials is None:
            print("Please enter Ti credentials.")
            username = getpass.getpass(prompt="Username: ")
            password = getpass.getpass(prompt="Password: ")
            self._credentials = (username, password)
        return self._credentials

    def _reset_credentials(self):
        self._credentials = None

    def _download(self, url, to_path):
        username, password = self._get_credentials()
        with self._session.get(url, stream=True, auth=(username, password)) as r:
            stream_to_path(r, to_path)
