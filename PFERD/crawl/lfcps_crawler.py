import os
import re
from collections.abc import Iterable
from datetime import datetime
from pathlib import PurePath
from re import Pattern
from typing import Optional, cast
from urllib.parse import unquote, urljoin

from bs4 import Tag

from .crawler import CrawlError, CrawlWarning, anoncritical
from .kit_ipd_crawler import KitIpdCrawler, KitIpdCrawlerSection, KitIpdFile, KitIpdFolder


class LfcpsCrawlerSection(KitIpdCrawlerSection):
    def target(self) -> str:
        target = self.s.get("target", "https://lfcps.org/course/lfcps-schedule.html")
        if not target.startswith(("https://", "http://")):
            self.invalid_value("target", target, "Should be a URL")
        return target

    def link_regex(self) -> Pattern[str]:
        regex = self.s.get("link_regex", r"^.*?[^/]+\.(pdf|kyx|zip)$")
        return re.compile(regex)


class LfcpsCrawler(KitIpdCrawler):
    """
    Crawls the schedule page of André Platzer's courses (https://lfcps.org/course/).

    Files in the schedule table are sorted into "Slides", "Code" and "Exercises".
    Files outside the table are only downloaded if they live next to the schedule
    page (e.g. the syllabus), so the site navigation and book links are skipped.
    """

    async def _fetch_items(self) -> Iterable[KitIpdFile | KitIpdFolder]:
        page, url = await self.get_page()

        heading = page.find(id="course-schedule")
        table = heading.find_next("table") if isinstance(heading, Tag) else None
        if not isinstance(table, Tag):
            raise CrawlError(f"No schedule table found on {url!r}")

        folders: dict[str, KitIpdFolder] = {}
        root: list[KitIpdFile | KitIpdFolder] = []
        seen: set[str] = set()

        def add(folder_name: str | None, file_url: str) -> None:
            if file_url in seen:
                return
            seen.add(file_url)
            file = KitIpdFile(unquote(os.path.basename(file_url)), file_url)
            if folder_name is None:
                root.append(file)
                return
            if folder_name not in folders:
                folders[folder_name] = KitIpdFolder(folder_name, [])
                root.append(folders[folder_name])
            folders[folder_name].entries.append(file)

        for row in cast(list[Tag], table.find_all("tr")):
            is_recitation = row.find(class_="recitation") is not None
            for link in self._file_links(row, url):
                if is_recitation:
                    add("Exercises", link[1])
                elif link[0] == "code":
                    add("Code", link[1])
                else:
                    add("Slides", link[1])

        table.decompose()
        course_dir = urljoin(url, ".")
        for _, file_url in self._file_links(page, url):
            if file_url.startswith(course_dir) and "/" not in file_url.removeprefix(course_dir):
                add(None, file_url)

        return root

    @anoncritical
    async def _download_file(
        self, parent: PurePath, file: KitIpdFile, etag: Optional[str], mtime: Optional[datetime]
    ) -> None:
        # The schedule contains dead links, which should not abort the whole crawl
        try:
            await super()._download_file(parent, file, etag, mtime)
        except CrawlError as e:
            raise CrawlWarning(str(e)) from e

    def _file_links(self, tag: Tag, url: str) -> list[tuple[str, str]]:
        """
        Returns (title, absolute url) of all links whose absolute url matches the link regex.
        """
        links = []
        for link in cast(list[Tag], tag.find_all("a", href=True)):
            file_url = urljoin(url, cast(str, link["href"]))
            if self._file_regex.match(file_url):
                links.append((cast(str, link.get("title", "")), file_url))
        return links
