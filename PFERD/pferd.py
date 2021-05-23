from typing import Dict, List, Optional

from rich.markup import escape

from .authenticator import Authenticator
from .authenticators import AUTHENTICATORS
from .config import Config, ConfigOptionError
from .crawler import Crawler, CrawlError
from .crawlers import CRAWLERS
from .logging import log


class PferdLoadError(Exception):
    pass


class Pferd:
    def __init__(self, config: Config, crawlers_to_run: Optional[List[str]]):
        """
        May throw PferdLoadError.
        """

        if crawlers_to_run is not None and len(crawlers_to_run) != len(set(crawlers_to_run)):
            raise PferdLoadError("Some crawlers were selected multiple times")

        self._config = config
        self._crawlers_to_run = crawlers_to_run

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

    def _load_crawlers(self) -> List[str]:
        names = []

        for name, section in self._config.crawler_sections():
            log.print(f"[bold bright_cyan]Loading[/] {escape(name)}")
            names.append(name)

            crawl_type = section.get("type")
            crawler_constructor = CRAWLERS.get(crawl_type)
            if crawler_constructor is None:
                raise ConfigOptionError(name, "type", f"Unknown crawler type: {crawl_type!r}")

            crawler = crawler_constructor(name, section, self._config, self._authenticators)
            self._crawlers[name] = crawler

        return names

    def _find_crawlers_to_run(self, loaded_crawlers: List[str]) -> List[str]:
        log.explain_topic("Deciding which crawlers to run")

        if self._crawlers_to_run is None:
            log.explain("No crawlers specified on CLI")
            log.explain("Running all loaded crawlers")
            return loaded_crawlers

        log.explain("Crawlers specified on CLI")

        names: List[str] = []  # With 'crawl:' prefix
        unknown_names = []  # Without 'crawl:' prefix

        for name in self._crawlers_to_run:
            section_name = f"crawl:{name}"
            if section_name in self._crawlers:
                log.explain(f"Found crawler section named {section_name!r}")
                names.append(section_name)
            else:
                log.explain(f"There's no crawler section named {section_name!r}")
                unknown_names.append(name)

        if unknown_names:
            if len(unknown_names) == 1:
                [name] = unknown_names
                raise PferdLoadError(f"There is no crawler named {name!r}")
            else:
                names_str = ", ".join(repr(name) for name in unknown_names)
                raise PferdLoadError(f"There are no crawlers named {names_str}")

        return names

    async def run(self) -> None:
        """
        May throw PferdLoadError or ConfigOptionError.
        """

        # These two functions must run inside the same event loop as the
        # crawlers, so that any new objects (like Conditions or Futures) can
        # obtain the correct event loop.
        self._load_authenticators()
        loaded_crawlers = self._load_crawlers()

        log.print("")

        for name in self._find_crawlers_to_run(loaded_crawlers):
            crawler = self._crawlers[name]

            log.print(f"[bold bright_cyan]Running[/] {escape(name)}")

            try:
                await crawler.run()
            except CrawlError as e:
                log.error(str(e))
            except Exception:
                log.unexpected_exception()
