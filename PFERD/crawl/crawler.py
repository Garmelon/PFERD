import asyncio
import os
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Coroutine
from datetime import datetime
from pathlib import Path, PurePath
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple, TypeVar

from ..auth import Authenticator
from ..config import Config, Section
from ..deduplicator import Deduplicator
from ..limiter import Limiter
from ..logging import ProgressBar, log
from ..output_dir import FileSink, FileSinkToken, OnConflict, OutputDirectory, OutputDirError, Redownload
from ..report import MarkConflictError, MarkDuplicateError, Report
from ..transformer import Transformer
from ..utils import ReusableAsyncContextManager, fmt_path


class CrawlWarning(Exception):
    pass


class CrawlError(Exception):
    pass


Wrapped = TypeVar("Wrapped", bound=Callable[..., None])


def noncritical(f: Wrapped) -> Wrapped:
    """
    Catches and logs a few noncritical exceptions occurring during the function
    call, mainly CrawlWarning.

    If any exception occurs during the function call, the crawler's error_free
    variable is set to False. This includes noncritical exceptions.

    Warning: Must only be applied to member functions of the Crawler class!
    """

    def wrapper(*args: Any, **kwargs: Any) -> None:
        if not (args and isinstance(args[0], Crawler)):
            raise RuntimeError("@noncritical must only applied to Crawler methods")

        crawler = args[0]

        try:
            f(*args, **kwargs)
        except (CrawlWarning, OutputDirError, MarkDuplicateError, MarkConflictError) as e:
            crawler.report.add_warning(str(e))
            log.warn(str(e))
            crawler.error_free = False
        except Exception as e:
            crawler.error_free = False
            crawler.report.add_error(str(e))
            raise

    return wrapper  # type: ignore


AWrapped = TypeVar("AWrapped", bound=Callable[..., Coroutine[Any, Any, Optional[Any]]])


def anoncritical(f: AWrapped) -> AWrapped:
    """
    An async version of @noncritical.

    Catches and logs a few noncritical exceptions occurring during the function
    call, mainly CrawlWarning.

    If any exception occurs during the function call, the crawler's error_free
    variable is set to False. This includes noncritical exceptions.

    Warning: Must only be applied to member functions of the Crawler class!
    """

    async def wrapper(*args: Any, **kwargs: Any) -> Optional[Any]:
        if not (args and isinstance(args[0], Crawler)):
            raise RuntimeError("@anoncritical must only applied to Crawler methods")

        crawler = args[0]

        try:
            return await f(*args, **kwargs)
        except (CrawlWarning, OutputDirError, MarkDuplicateError, MarkConflictError) as e:
            log.warn(str(e))
            crawler.error_free = False
            crawler.report.add_warning(str(e))
        except Exception as e:
            crawler.error_free = False
            crawler.report.add_error(str(e))
            raise

        return None

    return wrapper  # type: ignore


class CrawlToken(ReusableAsyncContextManager[ProgressBar]):
    def __init__(self, limiter: Limiter, path: PurePath):
        super().__init__()

        self._limiter = limiter
        self._path = path

    @property
    def path(self) -> PurePath:
        return self._path

    async def _on_aenter(self) -> ProgressBar:
        self._stack.callback(lambda: log.status("[bold cyan]", "Crawled", fmt_path(self._path)))
        await self._stack.enter_async_context(self._limiter.limit_crawl())
        bar = self._stack.enter_context(log.crawl_bar("[bold bright_cyan]", "Crawling", fmt_path(self._path)))

        return bar


class DownloadToken(ReusableAsyncContextManager[Tuple[ProgressBar, FileSink]]):
    def __init__(self, limiter: Limiter, fs_token: FileSinkToken, path: PurePath):
        super().__init__()

        self._limiter = limiter
        self._fs_token = fs_token
        self._path = path

    @property
    def path(self) -> PurePath:
        return self._path

    async def _on_aenter(self) -> Tuple[ProgressBar, FileSink]:
        await self._stack.enter_async_context(self._limiter.limit_download())
        sink = await self._stack.enter_async_context(self._fs_token)
        # The "Downloaded ..." message is printed in the output dir, not here
        bar = self._stack.enter_context(log.download_bar("[bold bright_cyan]", "Downloading",
                                                         fmt_path(self._path)))

        return bar, sink


class CrawlerSection(Section):
    def type(self) -> str:
        value = self.s.get("type")
        if value is None:
            self.missing_value("type")
        return value

    def skip(self) -> bool:
        return self.s.getboolean("skip", fallback=False)

    def output_dir(self, name: str) -> Path:
        name = name.removeprefix("crawl:")
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

    def tasks(self) -> int:
        value = self.s.getint("tasks", fallback=1)
        if value <= 0:
            self.invalid_value("tasks", value, "Must be greater than 0")
        return value

    def downloads(self) -> int:
        tasks = self.tasks()
        value = self.s.getint("downloads", fallback=None)
        if value is None:
            return tasks
        if value <= 0:
            self.invalid_value("downloads", value, "Must be greater than 0")
        if value > tasks:
            self.invalid_value("downloads", value, "Must not be greater than tasks")
        return value

    def task_delay(self) -> float:
        value = self.s.getfloat("task_delay", fallback=0.0)
        if value < 0:
            self.invalid_value("task_delay", value, "Must not be negative")
        return value

    def windows_paths(self) -> bool:
        on_windows = os.name == "nt"
        return self.s.getboolean("windows_paths", fallback=on_windows)

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
            task_limit=section.tasks(),
            download_limit=section.downloads(),
            task_delay=section.task_delay(),
        )

        self._deduplicator = Deduplicator(section.windows_paths())
        self._transformer = Transformer(section.transform())

        self._output_dir = OutputDirectory(
            config.default_section.working_dir() / section.output_dir(name),
            section.redownload(),
            section.on_conflict(),
        )

    @property
    def report(self) -> Report:
        return self._output_dir.report

    @property
    def prev_report(self) -> Optional[Report]:
        return self._output_dir.prev_report

    @property
    def output_dir(self) -> OutputDirectory:
        return self._output_dir

    @staticmethod
    async def gather(awaitables: Sequence[Awaitable[Any]]) -> List[Any]:
        """
        Similar to asyncio.gather. However, in the case of an exception, all
        still running tasks are cancelled and the exception is rethrown.

        This should always be preferred over asyncio.gather in crawler code so
        that an exception like CrawlError may actually stop the crawler.
        """

        tasks = [asyncio.ensure_future(aw) for aw in awaitables]
        result = asyncio.gather(*tasks)
        try:
            return await result
        except:  # noqa: E722
            for task in tasks:
                task.cancel()
            raise

    async def crawl(self, path: PurePath) -> Optional[CrawlToken]:
        log.explain_topic(f"Decision: Crawl {fmt_path(path)}")
        path = self._deduplicator.mark(path)
        self._output_dir.report.found(path)

        if self._transformer.transform(path) is None:
            log.explain("Answer: No")
            log.status("[bold bright_black]", "Ignored", fmt_path(path))
            return None

        log.explain("Answer: Yes")
        return CrawlToken(self._limiter, path)

    def should_try_download(
            self,
            path: PurePath,
            *,
            etag_differs: Optional[bool] = None,
            mtime: Optional[datetime] = None,
            redownload: Optional[Redownload] = None,
            on_conflict: Optional[OnConflict] = None,
    ) -> bool:
        log.explain_topic(f"Decision: Should Download {fmt_path(path)}")

        if self._transformer.transform(path) is None:
            log.explain("Answer: No (ignored)")
            return False

        should_download = self._output_dir.should_try_download(
            path,
            etag_differs=etag_differs,
            mtime=mtime,
            redownload=redownload,
            on_conflict=on_conflict
        )
        if should_download:
            log.explain("Answer: Yes")
            return True
        else:
            log.explain("Answer: No")
            return False

    async def download(
            self,
            path: PurePath,
            *,
            etag_differs: Optional[bool] = None,
            mtime: Optional[datetime] = None,
            redownload: Optional[Redownload] = None,
            on_conflict: Optional[OnConflict] = None,
    ) -> Optional[DownloadToken]:
        log.explain_topic(f"Decision: Download {fmt_path(path)}")
        path = self._deduplicator.mark(path)
        self._output_dir.report.found(path)

        transformed_path = self._transformer.transform(path)
        if transformed_path is None:
            log.explain("Answer: No")
            log.status("[bold bright_black]", "Ignored", fmt_path(path))
            return None

        fs_token = await self._output_dir.download(
            path,
            transformed_path,
            etag_differs=etag_differs,
            mtime=mtime,
            redownload=redownload,
            on_conflict=on_conflict
        )
        if fs_token is None:
            log.explain("Answer: No")
            return None

        log.explain("Answer: Yes")
        return DownloadToken(self._limiter, fs_token, path)

    async def _cleanup(self) -> None:
        log.explain_topic("Decision: Clean up files")
        if self.error_free:
            log.explain("No warnings or errors occurred during this run")
            log.explain("Answer: Yes")
            await self._output_dir.cleanup()
        else:
            log.explain("Warnings or errors occurred during this run")
            log.explain("Answer: No")

    @anoncritical
    async def run(self) -> None:
        """
        Start the crawling process. Call this function if you want to use a
        crawler.
        """

        with log.show_progress():
            self._output_dir.prepare()
            self._output_dir.load_prev_report()
            await self._run()
            await self._cleanup()
            self._output_dir.store_report()

    @abstractmethod
    async def _run(self) -> None:
        """
        Overwrite this function if you are writing a crawler.

        This function must not return before all crawling is complete. To crawl
        multiple things concurrently, asyncio.gather can be used.
        """

        pass

    def debug_transforms(self) -> None:
        self._output_dir.load_prev_report()

        if not self.prev_report:
            log.warn("Couldn't find or load old report")
            return

        seen: Set[PurePath] = set()
        for known in sorted(self.prev_report.found_paths):
            looking_at = list(reversed(known.parents)) + [known]
            for path in looking_at:
                if path in seen:
                    continue

                log.explain_topic(f"Transforming {fmt_path(path)}")
                self._transformer.transform(path)
                seen.add(path)
