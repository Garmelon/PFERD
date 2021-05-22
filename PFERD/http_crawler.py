import asyncio
from pathlib import PurePath

import aiohttp
from rich.markup import escape

from .config import Config
from .crawler import Crawler, CrawlerSection
from .logging import log
from .version import NAME, VERSION


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
