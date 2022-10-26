import asyncio
import datetime
import random
from pathlib import Path, PurePath
from typing import Optional

from ..config import Config
from .crawler import Crawler, CrawlerSection, anoncritical


class LocalCrawlerSection(CrawlerSection):
    def target(self) -> Path:
        value = self.s.get("target")
        if value is None:
            self.missing_value("target")
        return Path(value).expanduser()

    def crawl_delay(self) -> float:
        value = self.s.getfloat("crawl_delay", fallback=0.0)
        if value < 0:
            self.invalid_value("crawl_delay", value,
                               "Must not be negative")
        return value

    def download_delay(self) -> float:
        value = self.s.getfloat("download_delay", fallback=0.0)
        if value < 0:
            self.invalid_value("download_delay", value,
                               "Must not be negative")
        return value

    def download_speed(self) -> Optional[int]:
        value = self.s.getint("download_speed")
        if value is not None and value <= 0:
            self.invalid_value("download_speed", value,
                               "Must be greater than 0")
        return value


class LocalCrawler(Crawler):
    def __init__(
            self,
            name: str,
            section: LocalCrawlerSection,
            config: Config,
    ):
        super().__init__(name, section, config)

        self._target = config.default_section.working_dir() / section.target()
        self._crawl_delay = section.crawl_delay()
        self._download_delay = section.download_delay()
        self._download_speed = section.download_speed()

        if self._download_speed:
            self._block_size = self._download_speed // 10
        else:
            self._block_size = 1024**2  # 1 MiB

    async def _run(self) -> None:
        await self._crawl_path(self._target, PurePath())

    @anoncritical
    async def _crawl_path(self, path: Path, pure: PurePath) -> None:
        if path.is_dir():
            await self._crawl_dir(path, pure)
        elif path.is_file():
            await self._crawl_file(path, pure)

    async def _crawl_dir(self, path: Path, pure: PurePath) -> None:
        cl = await self.crawl(pure)
        if not cl:
            return

        async with cl:
            await asyncio.sleep(random.uniform(
                0.5 * self._crawl_delay,
                self._crawl_delay,
            ))

            for child in path.iterdir():
                pure_child = cl.path / child.name
                await self._crawl_path(child, pure_child)

    async def _crawl_file(self, path: Path, pure: PurePath) -> None:
        stat = path.stat()
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
        dl = await self.download(pure, mtime=mtime)
        if not dl:
            return

        async with dl as (bar, sink):
            await asyncio.sleep(random.uniform(
                0.5 * self._download_delay,
                self._download_delay,
            ))

            bar.set_total(stat.st_size)

            with open(path, "rb") as f:
                while True:
                    data = f.read(self._block_size)
                    if len(data) == 0:
                        break

                    sink.file.write(data)
                    bar.advance(len(data))

                    if self._download_speed:
                        delay = self._block_size / self._download_speed
                        delay = random.uniform(0.8 * delay, 1.2 * delay)
                        await asyncio.sleep(delay)

                sink.done()
