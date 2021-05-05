import configparser
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from pathlib import PurePath
# TODO In Python 3.9 and above, AsyncContextManager is deprecated
from typing import AsyncContextManager, AsyncIterator, Optional

from rich.markup import escape

from .conductor import ProgressBar, TerminalConductor
from .config import Config
from .limiter import Limiter
from .output_dir import OnConflict, OutputDirectory, Redownload
from .transformer import RuleParseException, Transformer


class CrawlerLoadException(Exception):
    pass


class Crawler(ABC):
    def __init__(
            self,
            name: str,
            config: Config,
            section: configparser.SectionProxy,
    ) -> None:
        """
        Initialize a crawler from its name and its section in the config file.

        If you are writing your own constructor for your own crawler, make sure
        to call this constructor first (via super().__init__).

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

        output_dir = config.working_dir / section.get("output_dir", name)
        redownload = Redownload.NEVER_SMART
        on_conflict = OnConflict.PROMPT
        self._output_dir = OutputDirectory(
            output_dir, redownload, on_conflict, self._conductor)

    def print(self, text: str) -> None:
        """
        Print rich markup to the terminal. Crawlers *must* use this function to
        print things unless they are holding an exclusive output context
        manager! Be careful to escape all user-supplied strings.
        """

        self._conductor.print(text)

    def exclusive_output(self) -> AsyncContextManager[None]:
        """
        Acquire exclusive rights™ to the terminal output. While this context
        manager is held, output such as printing and progress bars from other
        threads is suspended and the current thread may do whatever it wants
        with the terminal. However, it must return the terminal to its original
        state before exiting the context manager.

        No two threads can hold this context manager at the same time.

        Useful for password or confirmation prompts as well as running other
        programs while crawling (e. g. to get certain credentials).
        """

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

    def crawl_bar(self, path: PurePath) -> AsyncContextManager[ProgressBar]:
        pathstr = escape(str(path))
        desc = f"[bold magenta]Crawling[/bold magenta] {pathstr}"
        return self.progress_bar(desc)

    def download_bar(
            self,
            path: PurePath,
            size: int,
    ) -> AsyncContextManager[ProgressBar]:
        pathstr = escape(str(path))
        desc = f"[bold green]Downloading[/bold green] {pathstr}"
        return self.progress_bar(desc, total=size)

    async def run(self) -> None:
        """
        Start the crawling process. Call this function if you want to use a
        crawler.
        """

        async with self._conductor:
            await self.crawl()

    @abstractmethod
    async def crawl(self) -> None:
        """
        Overwrite this function if you are writing a crawler.

        This function must not return before all crawling is complete. To crawl
        multiple things concurrently, asyncio.gather can be used.
        """

        pass
