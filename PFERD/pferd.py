from typing import Dict

from rich import print
from rich.markup import escape

from .authenticator import Authenticator
from .authenticators import AUTHENTICATORS
from .conductor import TerminalConductor
from .config import Config
from .crawler import Crawler
from .crawlers import CRAWLERS


class PferdLoadException(Exception):
    pass


class Pferd:
    def __init__(self, config: Config):
        self._config = config
        self._conductor = TerminalConductor()
        self._authenticators: Dict[str, Authenticator] = {}
        self._crawlers: Dict[str, Crawler] = {}

    def _load_authenticators(self) -> None:
        abort = False
        for name, section in self._config.authenticator_sections():
            print(f"[bold bright_cyan]Loading[/] auth:{escape(name)}")
            authenticator_type = section.get("type")
            authenticator_constructor = AUTHENTICATORS.get(authenticator_type)
            if authenticator_constructor is None:
                abort = True
                t = escape(repr(authenticator_type))
                print(f"[red]Error: Unknown authenticator type {t}")
                continue

            authenticator = authenticator_constructor(
                name,
                section,
                self._config,
                self._conductor,
            )
            self._authenticators[name] = authenticator

        if abort:
            raise PferdLoadException()

    def _load_crawlers(self) -> None:
        abort = False
        for name, section in self._config.crawler_sections():
            print(f"[bold bright_cyan]Loading[/] crawler:{escape(name)}")
            crawler_type = section.get("type")
            crawler_constructor = CRAWLERS.get(crawler_type)
            if crawler_constructor is None:
                abort = True
                t = escape(repr(crawler_type))
                print(f"[red]Error: Unknown crawler type {t}")
                continue

            crawler = crawler_constructor(
                name,
                section,
                self._config,
                self._conductor,
                self._authenticators,
            )
            self._crawlers[name] = crawler

        if abort:
            raise PferdLoadException()

    async def run(self) -> None:
        try:
            self._load_authenticators()
            self._load_crawlers()
        except PferdLoadException:
            print("[bold red]Could not initialize PFERD properly")
            exit(1)

        for name, crawler in self._crawlers.items():
            print()
            print(f"[bold bright_cyan]Running[/] crawler:{escape(name)}")

            await crawler.run()
