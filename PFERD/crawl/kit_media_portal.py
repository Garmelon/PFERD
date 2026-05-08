from typing import cast

import aiohttp
from attr import dataclass
from bs4 import BeautifulSoup, Tag
from yarl import URL

from PFERD.crawl import CrawlError
from PFERD.crawl.crawler import CrawlWarning
from PFERD.logging import log
from PFERD.utils import soupify


@dataclass
class MediaPortalSoup:
    url: URL
    soup: BeautifulSoup

    def logged_in(self) -> bool:
        return self.soup.select_one(".page-login") is None


class MediaPortalPage:
    _media_soup: MediaPortalSoup
    _soup: BeautifulSoup

    def __init__(self, soup: MediaPortalSoup):
        self._soup = soup.soup
        self._media_soup = soup

    def get_video_url(self) -> str:
        source = self._soup.select_one("#media-element > source")
        if not source or "src" not in source.attrs:
            raise CrawlWarning(f"Video source not found for {self._media_soup.url}")
        return str(source["src"])


class MediaPortal:
    _session: aiohttp.ClientSession

    def __init__(self, session: aiohttp.ClientSession):
        self._session = session

    async def get_page(self, url: str) -> MediaPortalPage:
        soup = await self._get_soup(url)
        return MediaPortalPage(soup)

    async def _get_soup(self, url: str) -> MediaPortalSoup:
        async def try_it():
            res = await self._session.get(url)
            my_soup = MediaPortalSoup(url=res.url, soup=soupify(await res.read()))
            if my_soup.logged_in():
                return my_soup
            return None

        if soup := await try_it():
            return soup

        log.explain("Not logged in to KIT Media Library. Logging in")

        resp = await self._session.get("https://ilias-medien.bibliothek.kit.edu/auth", allow_redirects=True)
        body = soupify(await resp.read())
        target = cast(str, cast(Tag, body.select_one("form"))["action"])
        data = {}
        for elem in body.select("input"):
            if name := elem.get("name"):
                data[str(name)] = elem.get("value", "")
        resp = await self._session.post(target, data=data)
        soup = MediaPortalSoup(url=resp.url, soup=soupify(await resp.read()))

        if not soup.logged_in():
            raise CrawlError("Login to KIT Media Library failed.")

        retried = await try_it()
        if not retried:
            raise CrawlError("Login to KIT Media Library failed.")

        return retried
