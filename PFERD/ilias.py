# ILIAS

import aiohttp
import asyncio
import bs4
import logging
import pathlib
import re

from .organizer import Organizer
from .ilias_authenticators import ShibbolethAuthenticator
from . import utils

__all__ = [
    "ILIAS",
]
logger = logging.getLogger(__name__)

class ILIAS:
    FILE_RE = re.compile(r"goto\.php\?target=(file_\d+_download)")
    DIR_RE = re.compile(r"ilias\.php\?ref_id=(\d+)")

    def __init__(self, base_path, cookie_file):
        self.base_path = base_path

        self._auth = ShibbolethAuthenticator(base_path / cookie_file)

    async def synchronize(self, ref_id, to_dir, transform=lambda x: x, filter=lambda x: True):
        logging.info(f"    Synchronizing ref_id {ref_id} to {to_dir} using the ILIAS synchronizer.")

        sync_path = pathlib.Path(self.base_path, to_dir)
        orga = Organizer(self.base_path, sync_path)

        orga.clean_temp_dir()

        files = await self._crawl(pathlib.PurePath(), f"fold_{ref_id}", filter)
        await self._download(orga, files, transform)

        orga.clean_sync_dir()
        orga.clean_temp_dir()

    async def close(self):
        await self._auth.close()

    async def _crawl(self, dir_path, dir_id, filter_):
        soup = await self._auth.get_webpage(dir_id)

        found_files = []

        files = self._find_files(soup)
        for (name, file_id) in files:
            path = dir_path / name
            found_files.append((path, file_id))
            logger.debug(f"Found file {path}")

        dirs = self._find_dirs(soup)
        for (name, ref_id) in dirs:
            path = dir_path / name
            logger.debug(f"Found dir {path}")
            if filter_(path):
                logger.info(f"Searching {path}")
                files = await self._crawl(path, ref_id, filter_)
                found_files.extend(files)
            else:
                logger.info(f"Not searching {path}")

        return found_files

    async def _download(self, orga, files, transform):
        for (path, file_id) in sorted(files):
            to_path = transform(path)
            if to_path is not None:
                temp_path = orga.temp_file()
                await self._auth.download_file(file_id, temp_path)
                orga.add_file(temp_path, to_path)

    def _find_files(self, soup):
        files = []
        file_names = set()

        found = soup.find_all("a", {"class": "il_ContainerItemTitle", "href": self.FILE_RE})
        for element in found:
            file_stem = element.string.strip().replace("/", ".")
            file_type = element.parent.parent.parent.find("div", {"class": "il_ItemProperties"}).find("span").string.strip()
            file_id = re.search(self.FILE_RE, element.get("href")).group(1)

            file_name = f"{file_stem}.{file_type}"
            if file_name in file_names:
                counter = 1
                while True:
                    file_name = f"{file_stem} (duplicate {counter}).{file_type}"
                    if file_name in file_names:
                        counter += 1
                    else:
                        break

            files.append((file_name, file_id))
            file_names.add(file_name)

        return files

    def _find_dirs(self, soup):
        dirs = []

        found = soup.find_all("div", {"class": "alert", "role": "alert"})
        if found:
            return []

        found = soup.find_all("a", {"class": "il_ContainerItemTitle", "href": self.DIR_RE})
        for element in found:
            dir_name = element.string.strip().replace("/", ".")
            ref_id = re.search(self.DIR_RE, element.get("href")).group(1)
            dir_id = f"fold_{ref_id}"
            dirs.append((dir_name, dir_id))

        return dirs
