# Norberts Prog-Tuts

import logging
import pathlib
import re
import zipfile

import bs4
import requests

from .organizer import Organizer
from .utils import rename, stream_to_path

__all__ = [
    "Norbert",
]
logger = logging.getLogger(__name__)

class Norbert:
    BASE_URL = "https://studwww.informatik.kit.edu/~s_blueml/"
    LINK_RE = re.compile(r"^progtut/.*/(.*\.zip)$")

    def __init__(self, base_path):
        self.base_path = base_path

        self._session = requests.Session()

    def synchronize(self, to_dir, transform=lambda x: x, unzip=lambda _: True):
        logging.info(f"    Synchronizing to {to_dir} using the Norbert synchronizer.")

        sync_path = pathlib.Path(self.base_path, to_dir)
        orga = Organizer(self.base_path, sync_path)

        orga.clean_temp_dir()

        files = self._crawl()
        self._download(orga, files, transform, unzip)

        orga.clean_sync_dir()
        orga.clean_temp_dir()

    def _crawl(self):
        url = self.BASE_URL
        r = self._session.get(url)

        # replace undecodeable characters with a placeholder
        #text = r.raw.decode("utf-8", "replace")

        text = r.text
        soup = bs4.BeautifulSoup(text, "html.parser")

        files = []

        for found in soup.find_all("a", href=self.LINK_RE):
            url = found["href"]
            full_url = self.BASE_URL + url

            filename = re.search(self.LINK_RE, url).group(1)
            path = pathlib.PurePath(filename)

            logger.debug(f"Found zip file {filename} at {full_url}")
            files.append((path, full_url))

        return files

    def _download(self, orga, files, transform, unzip):
        for path, url in sorted(files):
            # Yes, we want the zip file contents
            if unzip(path):
                logger.debug(f"Downloading and unzipping {path}")
                zip_path = rename(path, path.stem)

                # Download zip file
                temp_file = orga.temp_file()
                self._download_zip(url, temp_file)

                # Search the zip file for files to extract
                temp_dir = orga.temp_dir()
                with zipfile.ZipFile(temp_file, "r") as zf:
                    for info in zf.infolist():
                        # Only interested in the files themselves, the directory
                        # structure is created automatically by orga.add_file()
                        if info.is_dir():
                            continue

                        file_path = zip_path / pathlib.PurePath(info.filename)
                        logger.debug(f"Found {info.filename} at path {file_path}")

                        new_path = transform(file_path)
                        if new_path is not None:
                            # Extract to temp file and add, the usual deal
                            temp_file = orga.temp_file()
                            extracted_path = zf.extract(info, temp_dir)
                            extracted_path = pathlib.Path(extracted_path)
                            orga.add_file(extracted_path, new_path)

            # No, we only want the zip file itself
            else:
                logger.debug(f"Only downloading {path}")

                new_path = transform(path)
                if new_path is not None:
                    temp_file = orga.temp_file()
                    self._download_zip(url, temp_file)
                    orga.add_file(temp_file, new_path)

    def _download_zip(self, url, to_path):
        with self._session.get(url, stream=True) as r:
            stream_to_path(r, to_path)
