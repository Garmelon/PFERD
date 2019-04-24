# Fakultät für Mathematik (FfM)

import aiohttp
import asyncio
import bs4
import logging
import pathlib
import re

from .organizer import Organizer
from . import utils

__all__ = [
    "FfM",
]
logger = logging.getLogger(__name__)

class FfM:
    BASE_URL = "http://www.math.kit.edu/"
    LINK_RE = re.compile(r"^https?://www.math.kit.edu/.*/(.*\.pdf)$")

    RETRY_ATTEMPTS = 5
    RETRY_DELAY = 1 # seconds

    def __init__(self, base_path):
        self.base_path = base_path

        self._session = aiohttp.ClientSession()

    async def synchronize(self, urlpart, to_dir, transform=lambda x: x):
        logging.info(f"    Synchronizing {urlpart} to {to_dir} using the FfM synchronizer.")

        sync_path = pathlib.Path(self.base_path, to_dir)
        orga = Organizer(self.base_path, sync_path)

        orga.clean_temp_dir()

        await self._crawl(orga, urlpart, transform)

        orga.clean_sync_dir()
        orga.clean_temp_dir()

    async def close(self):
        await self._session.close()

    async def _crawl(self, orga, urlpart, transform):
        url = self.BASE_URL + urlpart
        async with self._session.get(url) as resp:
            text = await resp.text()
        soup = bs4.BeautifulSoup(text, "html.parser")

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
            await self._download(url, temp_path)
            orga.add_file(temp_path, new_path)

    async def _download(self, url, to_path):
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
