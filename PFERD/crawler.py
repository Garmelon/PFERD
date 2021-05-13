from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path, PurePath
# TODO In Python 3.9 and above, AsyncContextManager is deprecated
from typing import (Any, AsyncContextManager, AsyncIterator, Awaitable,
                    Callable, Dict, Optional, TypeVar)

from rich.markup import escape

from .authenticator import Authenticator
from .conductor import ProgressBar, TerminalConductor
from .config import Config, Section
from .limiter import Limiter
from .output_dir import FileSink, OnConflict, OutputDirectory, Redownload
from .transformer import RuleParseException, Transformer


class CrawlerLoadException(Exception):
    pass


Wrapped = TypeVar("Wrapped", bound=Callable[..., None])


def noncritical(f: Wrapped) -> Wrapped:
    """
    Warning: Must only be applied to member functions of the Crawler class!

    Catches all exceptions occuring during the function call. If an exception
    occurs, the crawler's error_free variable is set to False.
    """

    def wrapper(self: "Crawler", *args: Any, **kwargs: Any) -> None:
        try:
            f(self, *args, **kwargs)
        except Exception as e:
            self.print(f"[red]Something went wrong: {escape(str(e))}")
            self.error_free = False
    return wrapper  # type: ignore


def repeat(attempts: int) -> Callable[[Wrapped], Wrapped]:
    """
    Warning: Must only be applied to member functions of the Crawler class!

    If an exception occurs during the function call, retries the function call
    a set amount of times. Exceptions that occur during the last attempt are
    not caught and instead passed on upwards.
    """

    def decorator(f: Wrapped) -> Wrapped:
        def wrapper(self: "Crawler", *args: Any, **kwargs: Any) -> None:
            for _ in range(attempts - 1):
                try:
                    f(self, *args, **kwargs)
                    return
                except Exception:
                    pass
            f(self, *args, **kwargs)
        return wrapper  # type: ignore
    return decorator


AWrapped = TypeVar("AWrapped", bound=Callable[..., Awaitable[None]])


def anoncritical(f: AWrapped) -> AWrapped:
    """
    An async version of @noncritical.
    Warning: Must only be applied to member functions of the Crawler class!

    Catches all exceptions occuring during the function call. If an exception
    occurs, the crawler's error_free variable is set to False.
    """

    async def wrapper(self: "Crawler", *args: Any, **kwargs: Any) -> None:
        try:
            await f(self, *args, **kwargs)
        except Exception as e:
            self.print(f"[red]Something went wrong: {escape(str(e))}")
            self.error_free = False
    return wrapper  # type: ignore


def arepeat(attempts: int) -> Callable[[AWrapped], AWrapped]:
    """
    An async version of @noncritical.
    Warning: Must only be applied to member functions of the Crawler class!

    If an exception occurs during the function call, retries the function call
    a set amount of times. Exceptions that occur during the last attempt are
    not caught and instead passed on upwards.
    """

    def decorator(f: AWrapped) -> AWrapped:
        async def wrapper(self: "Crawler", *args: Any, **kwargs: Any) -> None:
            for _ in range(attempts - 1):
                try:
                    await f(self, *args, **kwargs)
                    return
                except Exception:
                    pass
            await f(self, *args, **kwargs)
        return wrapper  # type: ignore
    return decorator


class CrawlerSection(Section):
    def output_dir(self, name: str) -> Path:
        return Path(self.s.get("output_dir", name)).expanduser()

    def redownload(self) -> Redownload:
        value = self.s.get("redownload", "never-smart")
        if value == "never":
            return Redownload.NEVER
        elif value == "never-smart":
            return Redownload.NEVER_SMART
        elif value == "always":
            return Redownload.ALWAYS
        elif value == "always-smart":
            return Redownload.ALWAYS_SMART
        self.invalid_value("redownload", value)

    def on_conflict(self) -> OnConflict:
        value = self.s.get("on_conflict", "prompt")
        if value == "prompt":
            return OnConflict.PROMPT
        elif value == "local-first":
            return OnConflict.LOCAL_FIRST
        elif value == "remote-first":
            return OnConflict.REMOTE_FIRST
        elif value == "no-delete":
            return OnConflict.NO_DELETE
        self.invalid_value("on_conflict", value)

    def transform(self) -> str:
        return self.s.get("transform", "")

    def auth(self, authenticators: Dict[str, Authenticator]) -> Authenticator:
        value = self.s.get("auth")
        if value is None:
            self.missing_value("auth")
        auth = authenticators.get(f"auth:{value}")
        if auth is None:
            self.invalid_value("auth", value)
        return auth


class Crawler(ABC):
    def __init__(
            self,
            name: str,
            section: CrawlerSection,
            config: Config,
            conductor: TerminalConductor,
    ) -> None:
        """
        Initialize a crawler from its name and its section in the config file.

        If you are writing your own constructor for your own crawler, make sure
        to call this constructor first (via super().__init__).

        May throw a CrawlerLoadException.
        """

        self.name = name
        self._conductor = conductor
        self._limiter = Limiter()
        self.error_free = True

        try:
            self._transformer = Transformer(section.transform())
        except RuleParseException as e:
            e.pretty_print()
            raise CrawlerLoadException()

        self._output_dir = OutputDirectory(
            config.working_dir / section.output_dir(name),
            section.redownload(),
            section.on_conflict(),
            self._conductor,
        )

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
            total: Optional[int] = None,
    ) -> AsyncContextManager[ProgressBar]:
        pathstr = escape(str(path))
        desc = f"[bold green]Downloading[/bold green] {pathstr}"
        return self.progress_bar(desc, total=total)

    async def download(
            self,
            path: PurePath,
            mtime: Optional[datetime] = None,
            redownload: Optional[Redownload] = None,
            on_conflict: Optional[OnConflict] = None,
    ) -> Optional[AsyncContextManager[FileSink]]:
        return await self._output_dir.download(
            path, mtime, redownload, on_conflict)

    async def cleanup(self) -> None:
        await self._output_dir.cleanup()

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
