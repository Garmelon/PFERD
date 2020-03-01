# Operating systems Exams

import getpass
import logging
import pathlib
import re

import bs4
import requests

from .organizer import Organizer
from .utils import stream_to_path, PrettyLogger

__all__ = ["OsExams"]
logger = logging.getLogger(__name__)
pretty = PrettyLogger(logger)

class OsExams:
    BASE_URL = "https://os.itec.kit.edu/deutsch/1556.php"
    LINK_RE = re.compile(
            r"^http://os.itec.kit.edu/downloads_own/sysarch-exam-assandsols"
            r".*/(.*\.pdf)$"
            )

    _credentials = None

    def __init__(self, base_path):
        self.base_path = base_path

        self._session = requests.Session()

    def synchronize(self, to_dir, transform=lambda x: x):
        pretty.starting_synchronizer(to_dir, "OsExams")

        sync_path = pathlib.Path(self.base_path, to_dir)

        orga = Organizer(self.base_path, sync_path)
        orga.clean_temp_dir()

        self._crawl(orga, transform)

        orga.clean_sync_dir()
        orga.clean_temp_dir()

    def _crawl(self, orga, transform):
        url = self.BASE_URL
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
        while True:
            username, password = self._get_credentials()
            with self._session.get(url, stream=True, auth=(username, password)) as r:
                if r.ok:
                    stream_to_path(r, to_path)
                    return
                else:
                    print("Incorrect credentials.")
                    self._reset_credentials()

    def _get_credentials(self):
        if self._credentials is None:
            print("Please enter OS credentials.")
            username = getpass.getpass(prompt="Username: ")
            password = getpass.getpass(prompt="Password: ")
            self._credentials = (username, password)
        return self._credentials

    def _reset_credentials(self):
        self._credentials = None
