# Norberts Prog-Tuts

import aiohttp
import asyncio
import bs4
import logging
import pathlib
import re
import zipfile

from .organizer import Organizer
from . import utils

__all__ = [
    "Norbert",
]
logger = logging.getLogger(__name__)

class Norbert:
    BASE_URL = "https://studwww.informatik.kit.edu/~s_blueml/"
    LINK_RE = re.compile(r"^progtut/.*/(.*\.zip)$")

    RETRY_ATTEMPTS = 5
    RETRY_DELAY = 1 # seconds

    def __init__(self, base_path):
        self.base_path = base_path

        self._session = aiohttp.ClientSession()

    async def synchronize(self, to_dir, transform=lambda x: x, unzip=lambda _: True):
        logging.info(f"    Synchronizing to {to_dir} using the Norbert synchronizer.")

        sync_path = pathlib.Path(self.base_path, to_dir)
        orga = Organizer(self.base_path, sync_path)

        orga.clean_temp_dir()

        files = await self._crawl()
        await self._download(orga, files, transform, unzip)

        orga.clean_sync_dir()
        orga.clean_temp_dir()

    async def close(self):
        await self._session.close()

    async def _crawl(self):
        url = self.BASE_URL
        async with self._session.get(url) as resp:
            raw = await resp.read()
            # replace undecodeable characters with a placeholder
            text = raw.decode("utf-8", "replace")
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

    async def _download(self, orga, files, transform, unzip):
        for path, url in sorted(files):
            # Yes, we want the zip file contents
            if unzip(path):
                logger.debug(f"Downloading and unzipping {path}")
                zip_path = utils.rename(path, path.stem)

                # Download zip file
                temp_file = orga.temp_file()
                await self._download_zip(url, temp_file)

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
                    await self._download_zip(url, temp_file)
                    orga.add_file(temp_file, new_path)

    async def _download_zip(self, url, to_path):
        for t in range(self.RETRY_ATTEMPTS):
            try:
                async with self._session.get(url) as resp:
                    await utils.stream_to_path(resp, to_path)
            except aiohttp.client_exceptions.ServerDisconnectedError:
                logger.debug(f"Try {t+1} out of {self.RETRY_ATTEMPTS} failed, retrying in {self.RETRY_DELAY} s")
                await asyncio.sleep(self.RETRY_DELAY)
            else:
                return
        else:
            logger.error(f"Could not download {url}")
            raise utils.OutOfTriesException(f"Try {self.RETRY_ATTEMPTS} out of {self.RETRY_ATTEMPTS} failed.")
