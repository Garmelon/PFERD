import os
import re
from collections.abc import Awaitable, Generator, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath
from re import Pattern
from typing import Any, Optional, Union, cast
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup, Tag

from ..auth import Authenticator
from ..config import Config
from ..logging import ProgressBar, log
from ..output_dir import FileSink
from ..utils import sanitize_path_name, soupify
from .crawler import CrawlError
from .http_crawler import HttpCrawler, HttpCrawlerSection


class KitIpdCrawlerSection(HttpCrawlerSection):
    def target(self) -> str:
        target = self.s.get("target")
        if not target:
            self.missing_value("target")

        if not target.startswith("https://"):
            self.invalid_value("target", target, "Should be a URL")

        return target

    def link_regex(self) -> Pattern[str]:
        regex = self.s.get("link_regex", r"^.*?[^/]+\.(pdf|zip|c|cpp|java)$")
        return re.compile(regex)

    def basic_auth(self, authenticators: dict[str, Authenticator]) -> Optional[Authenticator]:
        value: Optional[str] = self.s.get("auth")
        if value is None:
            return None
        auth = authenticators.get(value)
        if auth is None:
            self.invalid_value("auth", value, "No such auth section exists")
        return auth


@dataclass
class KitIpdFile:
    name: str
    url: str

    def explain(self) -> None:
        log.explain(f"File {self.name!r} (href={self.url!r})")


@dataclass
class KitIpdFolder:
    name: str
    entries: list[Union[KitIpdFile, "KitIpdFolder"]]

    def explain(self) -> None:
        log.explain_topic(f"Folder {self.name!r}")
        for entry in self.entries:
            entry.explain()


class KitIpdCrawler(HttpCrawler):
    def __init__(
        self,
        name: str,
        section: KitIpdCrawlerSection,
        config: Config,
        authenticators: dict[str, Authenticator],
    ):
        super().__init__(name, section, config)
        self._url = section.target()
        self._file_regex = section.link_regex()
        self._authenticator = section.basic_auth(authenticators)
        self._basic_auth: Optional[aiohttp.BasicAuth] = None

    async def _run(self) -> None:
        if self._authenticator:
            username, password = await self._authenticator.credentials()
            self._basic_auth = aiohttp.BasicAuth(username, password)

        maybe_cl = await self.crawl(PurePath("."))
        if not maybe_cl:
            return

        tasks: list[Awaitable[None]] = []

        async with maybe_cl:
            for item in await self._fetch_items():
                item.explain()
                if isinstance(item, KitIpdFolder):
                    tasks.append(self._crawl_folder(PurePath("."), item))
                else:
                    log.explain_topic(f"Orphan file {item.name!r} (href={item.url!r})")
                    log.explain("Attributing it to root folder")
                    # do this here to at least be sequential and not parallel (rate limiting is hard, as the
                    # crawl abstraction does not hold for these requests)
                    etag, mtime = await self._request_resource_version(item.url)
                    tasks.append(self._download_file(PurePath("."), item, etag, mtime))

        await self.gather(tasks)

    async def _crawl_folder(self, parent: PurePath, folder: KitIpdFolder) -> None:
        path = parent / sanitize_path_name(folder.name)
        if not await self.crawl(path):
            return

        tasks = []
        for entry in folder.entries:
            if isinstance(entry, KitIpdFolder):
                tasks.append(self._crawl_folder(path, entry))
            else:
                # do this here to at least be sequential and not parallel (rate limiting is hard, as the crawl
                # abstraction does not hold for these requests)
                etag, mtime = await self._request_resource_version(entry.url)
                tasks.append(self._download_file(path, entry, etag, mtime))

        await self.gather(tasks)

    async def _download_file(
        self, parent: PurePath, file: KitIpdFile, etag: Optional[str], mtime: Optional[datetime]
    ) -> None:
        element_path = parent / sanitize_path_name(file.name)

        prev_etag = self._get_previous_etag_from_report(element_path)
        etag_differs = None if prev_etag is None else prev_etag != etag

        maybe_dl = await self.download(element_path, etag_differs=etag_differs, mtime=mtime)
        if not maybe_dl:
            # keep storing the known file's etag
            if prev_etag:
                self._add_etag_to_report(element_path, prev_etag)
            return

        async with maybe_dl as (bar, sink):
            await self._stream_from_url(file.url, element_path, sink, bar)

    async def _fetch_items(self) -> Iterable[KitIpdFile | KitIpdFolder]:
        page, url = await self.get_page()
        elements: list[Tag] = self._find_file_links(page)

        # do not add unnecessary nesting for a single <h1> heading
        drop_h1: bool = len(page.find_all(name="h1")) <= 1

        folder_tree: KitIpdFolder = KitIpdFolder(".", [])
        for element in elements:
            parent = HttpCrawler.get_folder_structure_from_heading_hierarchy(element, drop_h1)
            file = self._extract_file(element, url)

            current_folder: KitIpdFolder = folder_tree
            for folder_name in parent.parts:
                # helps the type checker to verify that current_folder is indeed a folder
                def subfolders() -> Generator[KitIpdFolder, Any, None]:
                    return (entry for entry in current_folder.entries if isinstance(entry, KitIpdFolder))

                if not any(entry.name == folder_name for entry in subfolders()):
                    current_folder.entries.append(KitIpdFolder(folder_name, []))
                current_folder = next(entry for entry in subfolders() if entry.name == folder_name)

            current_folder.entries.append(file)

        return folder_tree.entries

    def _extract_file(self, link: Tag, url: str) -> KitIpdFile:
        url = self._abs_url_from_link(url, link)
        name = os.path.basename(url)
        return KitIpdFile(name, url)

    def _find_file_links(self, tag: Tag | BeautifulSoup) -> list[Tag]:
        return cast(list[Tag], tag.find_all(name="a", attrs={"href": self._file_regex}))

    def _abs_url_from_link(self, url: str, link_tag: Tag) -> str:
        return urljoin(url, cast(str, link_tag.get("href")))

    async def _stream_from_url(self, url: str, path: PurePath, sink: FileSink, bar: ProgressBar) -> None:
        async with self.session.get(url, allow_redirects=False, auth=self._basic_auth) as resp:
            if resp.status == 403:
                raise CrawlError("Received a 403. Are you within the KIT network/VPN?")
            if resp.status == 401:
                raise CrawlError("Received a 401. Do you maybe need credentials?")
            if resp.status >= 400:
                raise CrawlError(f"Received HTTP {resp.status} when trying to download {url!r}")

            if resp.content_length:
                bar.set_total(resp.content_length)

            async for data in resp.content.iter_chunked(1024):
                sink.file.write(data)
                bar.advance(len(data))

            sink.done()

            self._add_etag_to_report(path, resp.headers.get("ETag"))

    async def get_page(self) -> tuple[BeautifulSoup, str]:
        async with self.session.get(self._url, auth=self._basic_auth) as request:
            # The web page for Algorithmen für Routenplanung contains some
            # weird comments that beautifulsoup doesn't parse correctly. This
            # hack enables those pages to be crawled, and should hopefully not
            # cause issues on other pages.
            content = (await request.read()).decode("utf-8")
            content = re.sub(r"<!--.*?-->", "", content)
            return soupify(content.encode("utf-8")), str(request.url)
