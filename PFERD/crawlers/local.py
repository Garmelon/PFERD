import asyncio
from pathlib import Path, PurePath

from ..config import Config
from ..crawler import Crawler, CrawlerSection, anoncritical


class LocalCrawlerSection(CrawlerSection):
    def path(self) -> Path:
        value = self.s.get("path")
        if value is None:
            self.missing_value("path")
        return Path(value).expanduser()


class LocalCrawler(Crawler):
    def __init__(
            self,
            name: str,
            config: Config,
            section: LocalCrawlerSection,
    ):
        super().__init__(name, config, section)

        self._path = section.path()

    async def crawl(self) -> None:
        await self._crawl_path(self._path, PurePath())
        if self.error_free:
            self.cleanup()

    @anoncritical
    async def _crawl_path(self, path: Path, pure: PurePath) -> None:
        if path.is_dir():
            await self._crawl_dir(path, pure)
        elif path.is_file():
            await self._crawl_file(path, pure)

    async def _crawl_dir(self, path: Path, pure: PurePath) -> None:
        tasks = []
        async with self.crawl_bar(pure):
            for child in path.iterdir():
                pure_child = pure / child.name
                tasks.append(self._crawl_path(child, pure_child))
        await asyncio.gather(*tasks)

    async def _crawl_file(self, path: Path, pure: PurePath) -> None:
        async with self.download_bar(path) as bar:
            bar.set_total(path.stat().st_size)

            dl = await self.download(pure)
            if not dl:
                return

            async with dl as sink:
                with open(path, "rb") as f:
                    while True:
                        data = f.read(1024**2)
                        if len(data) == 0:
                            break
                        sink.file.write(data)
                        bar.advance(len(data))
                    sink.done()
