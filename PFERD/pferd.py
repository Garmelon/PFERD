from typing import Dict

from rich.markup import escape

from .authenticator import Authenticator
from .authenticators import AUTHENTICATORS
from .config import Config, ConfigOptionError
from .crawler import Crawler, CrawlError
from .crawlers import CRAWLERS
from .logging import log


class Pferd:
    def __init__(self, config: Config):
        """
        May throw ConfigOptionError.
        """

        self._config = config
        self._authenticators: Dict[str, Authenticator] = {}
        self._crawlers: Dict[str, Crawler] = {}

    def _load_authenticators(self) -> None:
        for name, section in self._config.authenticator_sections():
            log.print(f"[bold bright_cyan]Loading[/] {escape(name)}")
            auth_type = section.get("type")
            authenticator_constructor = AUTHENTICATORS.get(auth_type)
            if authenticator_constructor is None:
                raise ConfigOptionError(name, "type", f"Unknown authenticator type: {auth_type!r}")

            authenticator = authenticator_constructor(name, section, self._config)
            self._authenticators[name] = authenticator

    def _load_crawlers(self) -> None:
        for name, section in self._config.crawler_sections():
            log.print(f"[bold bright_cyan]Loading[/] {escape(name)}")
            crawl_type = section.get("type")
            crawler_constructor = CRAWLERS.get(crawl_type)
            if crawler_constructor is None:
                raise ConfigOptionError(name, "type", f"Unknown crawler type: {crawl_type!r}")

            crawler = crawler_constructor(name, section, self._config, self._authenticators)
            self._crawlers[name] = crawler

    async def run(self) -> None:
        # These two functions must run inside the same event loop as the
        # crawlers, so that any new objects (like Conditions or Futures) can
        # obtain the correct event loop.
        self._load_authenticators()
        self._load_crawlers()

        for name, crawler in self._crawlers.items():
            log.print("")
            log.print(f"[bold bright_cyan]Running[/] {escape(name)}")

            try:
                await crawler.run()
            except CrawlError as e:
                log.error(str(e))
            except Exception:
                log.unexpected_exception()
