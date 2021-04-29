import configparser
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from pathlib import Path
# TODO In Python 3.9 and above, AsyncContextManager is deprecated
from typing import AsyncContextManager, AsyncIterator, Optional

from rich.markup import escape

from .conductor import ProgressBar, TerminalConductor
from .limiter import Limiter
from .transformer import RuleParseException, Transformer


class CrawlerLoadException(Exception):
    pass


class Crawler(ABC):
    def __init__(self, name: str, section: configparser.SectionProxy) -> None:
        """
        May throw a CrawlerLoadException.
        """

        self.name = name

        self._conductor = TerminalConductor()
        self._limiter = Limiter()

        try:
            self._transformer = Transformer(section.get("transform", ""))
        except RuleParseException as e:
            e.pretty_print()
            raise CrawlerLoadException()

        # output_dir = Path(section.get("output_dir", name))

    def print(self, text: str) -> None:
        self._conductor.print(text)

    def exclusive_output(self):
        return self._conductor.exclusive_output()

    @asynccontextmanager
    async def progress_bar(
            self,
            desc: str,
            total: Optional[int] = None,
    ) -> AsyncIterator[ProgressBar]:
        async with self._limiter.limit():
            with self._conductor.progress_bar(desc, total=total) as bar:
                yield bar

    def crawl_bar(self, path: Path) -> AsyncContextManager[ProgressBar]:
        pathstr = escape(str(path))
        desc = f"[bold magenta]Crawling[/bold magenta] {pathstr}"
        return self.progress_bar(desc)

    def download_bar(
            self,
            path: Path,
            size: int,
    ) -> AsyncContextManager[ProgressBar]:
        pathstr = escape(str(path))
        desc = f"[bold green]Downloading[/bold green] {pathstr}"
        return self.progress_bar(desc, total=size)

    async def run(self) -> None:
        async with self._conductor:
            await self.crawl()

    @abstractmethod
    async def crawl(self) -> None:
        pass
