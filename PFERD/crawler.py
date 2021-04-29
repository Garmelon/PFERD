import configparser
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional

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

    @asynccontextmanager
    async def progress_bar(
            self,
            path: Path,
            total: Optional[int] = None,
    ) -> AsyncIterator[ProgressBar]:
        desc = escape(str(path))
        async with self._limiter.limit():
            with self._conductor.progress_bar(desc, total=total) as bar:
                yield bar

    async def run(self) -> None:
        await self._conductor.start()
        try:
            await self.crawl()
        finally:
            await self._conductor.stop()

    @abstractmethod
    async def crawl(self) -> None:
        pass
