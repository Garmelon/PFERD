import asyncio
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path, PurePath
# TODO In Python 3.9 and above, AsyncContextManager is deprecated
from typing import Any, AsyncContextManager, AsyncIterator, Awaitable, Callable, Dict, Optional, TypeVar

import aiohttp
from rich.markup import escape

from .authenticator import Authenticator
from .config import Config, Section
from .limiter import Limiter
from .logging import ProgressBar, log
from .output_dir import FileSink, OnConflict, OutputDirectory, OutputDirError, Redownload
from .report import MarkConflictError, MarkDuplicateError
from .transformer import Transformer
from .version import NAME, VERSION


class CrawlWarning(Exception):
    pass


class CrawlError(Exception):
    pass


Wrapped = TypeVar("Wrapped", bound=Callable[..., None])


def noncritical(f: Wrapped) -> Wrapped:
    """
    Catches all exceptions occuring during the function call. If an exception
    occurs, the crawler's error_free variable is set to False.

    Warning: Must only be applied to member functions of the Crawler class!
    """

    def wrapper(*args: Any, **kwargs: Any) -> None:
        if not (args and isinstance(args[0], Crawler)):
            raise RuntimeError("@noncritical must only applied to Crawler methods")

        crawler = args[0]

        try:
            f(*args, **kwargs)
        except (CrawlWarning, OutputDirError, MarkDuplicateError, MarkConflictError) as e:
            log.warn(str(e))
            crawler.error_free = False
        except CrawlError:
            crawler.error_free = False
            raise

    return wrapper  # type: ignore


AWrapped = TypeVar("AWrapped", bound=Callable[..., Awaitable[None]])


def anoncritical(f: AWrapped) -> AWrapped:
    """
    An async version of @noncritical.

    Catches all exceptions occuring during the function call. If an exception
    occurs, the crawler's error_free variable is set to False.

    Warning: Must only be applied to member functions of the Crawler class!
    """

    async def wrapper(*args: Any, **kwargs: Any) -> None:
        if not (args and isinstance(args[0], Crawler)):
            raise RuntimeError("@anoncritical must only applied to Crawler methods")

        crawler = args[0]

        try:
            await f(*args, **kwargs)
        except CrawlWarning as e:
            log.print(f"[bold bright_red]Warning[/] {escape(str(e))}")
            crawler.error_free = False
        except CrawlError as e:
            log.print(f"[bold bright_red]Error[/] [red]{escape(str(e))}")
            crawler.error_free = False
            raise

    return wrapper  # type: ignore


class CrawlerSection(Section):
    def output_dir(self, name: str) -> Path:
        # TODO Use removeprefix() after switching to 3.9
        if name.startswith("crawl:"):
            name = name[len("crawl:"):]
        return Path(self.s.get("output_dir", name)).expanduser()

    def redownload(self) -> Redownload:
        value = self.s.get("redownload", "never-smart")
        try:
            return Redownload.from_string(value)
        except ValueError as e:
            self.invalid_value(
                "redownload",
                value,
                str(e).capitalize(),
            )

    def on_conflict(self) -> OnConflict:
        value = self.s.get("on_conflict", "prompt")
        try:
            return OnConflict.from_string(value)
        except ValueError as e:
            self.invalid_value(
                "on_conflict",
                value,
                str(e).capitalize(),
            )

    def transform(self) -> str:
        return self.s.get("transform", "")

    def max_concurrent_tasks(self) -> int:
        value = self.s.getint("max_concurrent_tasks", fallback=1)
        if value <= 0:
            self.invalid_value("max_concurrent_tasks", value,
                               "Must be greater than 0")
        return value

    def max_concurrent_downloads(self) -> int:
        tasks = self.max_concurrent_tasks()
        value = self.s.getint("max_concurrent_downloads", fallback=None)
        if value is None:
            return tasks
        if value <= 0:
            self.invalid_value("max_concurrent_downloads", value,
                               "Must be greater than 0")
        if value > tasks:
            self.invalid_value("max_concurrent_downloads", value,
                               "Must not be greater than max_concurrent_tasks")
        return value

    def delay_between_tasks(self) -> float:
        value = self.s.getfloat("delay_between_tasks", fallback=0.0)
        if value < 0:
            self.invalid_value("delay_between_tasks", value,
                               "Must not be negative")
        return value

    def auth(self, authenticators: Dict[str, Authenticator]) -> Authenticator:
        value = self.s.get("auth")
        if value is None:
            self.missing_value("auth")
        auth = authenticators.get(value)
        if auth is None:
            self.invalid_value("auth", value, "No such auth section exists")
        return auth


class Crawler(ABC):
    def __init__(
            self,
            name: str,
            section: CrawlerSection,
            config: Config,
    ) -> None:
        """
        Initialize a crawler from its name and its section in the config file.

        If you are writing your own constructor for your own crawler, make sure
        to call this constructor first (via super().__init__).

        May throw a CrawlerLoadException.
        """

        self.name = name
        self.error_free = True

        self._limiter = Limiter(
            task_limit=section.max_concurrent_tasks(),
            download_limit=section.max_concurrent_downloads(),
            task_delay=section.delay_between_tasks(),
        )

        self._transformer = Transformer(section.transform())

        self._output_dir = OutputDirectory(
            config.default_section.working_dir() / section.output_dir(name),
            section.redownload(),
            section.on_conflict(),
        )

    @asynccontextmanager
    async def crawl_bar(
            self,
            path: PurePath,
            total: Optional[int] = None,
    ) -> AsyncIterator[ProgressBar]:
        desc = f"[bold bright_cyan]Crawling[/] {escape(str(path))}"
        async with self._limiter.limit_crawl():
            with log.crawl_bar(desc, total=total) as bar:
                yield bar

    @asynccontextmanager
    async def download_bar(
            self,
            path: PurePath,
            total: Optional[int] = None,
    ) -> AsyncIterator[ProgressBar]:
        desc = f"[bold bright_cyan]Downloading[/] {escape(str(path))}"
        async with self._limiter.limit_download():
            with log.download_bar(desc, total=total) as bar:
                yield bar

    def should_crawl(self, path: PurePath) -> bool:
        return self._transformer.transform(path) is not None

    async def download(
            self,
            path: PurePath,
            mtime: Optional[datetime] = None,
            redownload: Optional[Redownload] = None,
            on_conflict: Optional[OnConflict] = None,
    ) -> Optional[AsyncContextManager[FileSink]]:
        transformed_path = self._transformer.transform(path)
        if transformed_path is None:
            return None

        return await self._output_dir.download(
            transformed_path, mtime, redownload, on_conflict)

    async def cleanup(self) -> None:
        await self._output_dir.cleanup()

    async def run(self) -> None:
        """
        Start the crawling process. Call this function if you want to use a
        crawler.
        """

        with log.show_progress():
            await self.crawl()

    @abstractmethod
    async def crawl(self) -> None:
        """
        Overwrite this function if you are writing a crawler.

        This function must not return before all crawling is complete. To crawl
        multiple things concurrently, asyncio.gather can be used.
        """

        pass


class HttpCrawler(Crawler):
    COOKIE_FILE = PurePath(".cookies")

    def __init__(
            self,
            name: str,
            section: CrawlerSection,
            config: Config,
    ) -> None:
        super().__init__(name, section, config)

        self._cookie_jar_path = self._output_dir.resolve(self.COOKIE_FILE)
        self._output_dir.register_reserved(self.COOKIE_FILE)
        self._authentication_id = 0
        self._authentication_lock = asyncio.Lock()

    async def prepare_request(self) -> int:
        # We acquire the lock here to ensure we wait for any concurrent authenticate to finish.
        # This should reduce the amount of requests we make: If an authentication is in progress
        # all future requests wait for authentication to complete.
        async with self._authentication_lock:
            return self._authentication_id

    async def authenticate(self, current_id: int) -> None:
        async with self._authentication_lock:
            # Another thread successfully called authenticate in between
            # We do not want to perform auth again, so return here. We can
            # assume auth suceeded as authenticate will throw an error if
            # it failed.
            if current_id != self._authentication_id:
                return
            await self._authenticate()
            self._authentication_id += 1

    async def _authenticate(self) -> None:
        """
        Performs authentication. This method must only return normally if authentication suceeded.
        In all other cases it mus either retry internally or throw a terminal exception.
        """
        raise RuntimeError("_authenticate() was called but crawler doesn't provide an implementation")

    async def run(self) -> None:
        cookie_jar = aiohttp.CookieJar()

        try:
            cookie_jar.load(self._cookie_jar_path)
        except Exception:
            pass

        async with aiohttp.ClientSession(
                headers={"User-Agent": f"{NAME}/{VERSION}"},
                cookie_jar=cookie_jar,
        ) as session:
            self.session = session
            try:
                await super().run()
            finally:
                del self.session

        try:
            cookie_jar.save(self._cookie_jar_path)
        except Exception:
            log.print(f"[bold red]Warning:[/] Failed to save cookies to {escape(str(self.COOKIE_FILE))}")


def repeat(attempts: int) -> Callable[[Wrapped], Wrapped]:
    """Deprecated."""
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


def arepeat(attempts: int) -> Callable[[AWrapped], AWrapped]:
    """Deprecated."""
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
