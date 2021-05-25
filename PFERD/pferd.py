from pathlib import Path
from typing import Dict, List, Optional

from rich.markup import escape

from .auth import AUTHENTICATORS, Authenticator, AuthError
from .config import Config, ConfigOptionError
from .crawl import CRAWLERS, Crawler, CrawlError, KitIliasWebCrawler
from .logging import log
from .utils import fmt_path


class PferdLoadError(Exception):
    pass


class Pferd:
    def __init__(self, config: Config, cli_crawlers: Optional[List[str]]):
        """
        May throw PferdLoadError.
        """

        self._config = config
        self._crawlers_to_run = self._find_crawlers_to_run(config, cli_crawlers)

        self._authenticators: Dict[str, Authenticator] = {}
        self._crawlers: Dict[str, Crawler] = {}

    def _find_crawlers_to_run(self, config: Config, cli_crawlers: Optional[List[str]]) -> List[str]:
        log.explain_topic("Deciding which crawlers to run")
        crawl_sections = [name for name, _ in config.crawler_sections()]

        if cli_crawlers is None:
            log.explain("No crawlers specified on CLI")
            log.explain("Running all crawlers specified in config")
            return crawl_sections

        if len(cli_crawlers) != len(set(cli_crawlers)):
            raise PferdLoadError("Some crawlers were selected multiple times")

        log.explain("Crawlers specified on CLI")

        crawlers_to_run = []  # With crawl: prefix
        unknown_names = []  # Without crawl: prefix

        for name in cli_crawlers:
            section_name = f"crawl:{name}"
            if section_name in crawl_sections:
                log.explain(f"Crawler section named {section_name!r} exists")
                crawlers_to_run.append(section_name)
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

        return crawlers_to_run

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
        # Cookie sharing
        kit_ilias_web_paths: Dict[Authenticator, List[Path]] = {}

        for name, section in self._config.crawler_sections():
            log.print(f"[bold bright_cyan]Loading[/] {escape(name)}")

            crawl_type = section.get("type")
            crawler_constructor = CRAWLERS.get(crawl_type)
            if crawler_constructor is None:
                raise ConfigOptionError(name, "type", f"Unknown crawler type: {crawl_type!r}")

            crawler = crawler_constructor(name, section, self._config, self._authenticators)
            self._crawlers[name] = crawler

            if self._config.default_section.share_cookies():
                if isinstance(crawler, KitIliasWebCrawler):
                    crawler.share_cookies(kit_ilias_web_paths)

    async def run(self) -> None:
        """
        May throw ConfigOptionError.
        """

        # These two functions must run inside the same event loop as the
        # crawlers, so that any new objects (like Conditions or Futures) can
        # obtain the correct event loop.
        self._load_authenticators()
        self._load_crawlers()

        log.print("")

        for name in self._crawlers_to_run:
            crawler = self._crawlers[name]

            log.print(f"[bold bright_cyan]Running[/] {escape(name)}")

            try:
                await crawler.run()
            except (CrawlError, AuthError) as e:
                log.error(str(e))
            except Exception:
                log.unexpected_exception()

    def print_report(self) -> None:
        for name in self._crawlers_to_run:
            crawler = self._crawlers.get(name)
            if crawler is None:
                continue  # Crawler failed to load

            log.report("")
            log.report(f"[bold bright_cyan]Report[/] for {escape(name)}")

            something_changed = False
            for path in sorted(crawler.report.added_files):
                something_changed = True
                log.report(f"  [bold bright_green]Added[/] {fmt_path(path)}")
            for path in sorted(crawler.report.changed_files):
                something_changed = True
                log.report(f"  [bold bright_yellow]Changed[/] {fmt_path(path)}")
            for path in sorted(crawler.report.deleted_files):
                something_changed = True
                log.report(f"  [bold bright_magenta]Deleted[/] {fmt_path(path)}")

            if not something_changed:
                log.report("  Nothing changed")
