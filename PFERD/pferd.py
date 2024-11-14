from pathlib import Path, PurePath
from typing import Dict, List, Optional

from rich.markup import escape

from .auth import AUTHENTICATORS, Authenticator, AuthError, AuthSection
from .config import Config, ConfigOptionError
from .crawl import CRAWLERS, Crawler, CrawlError, CrawlerSection, KitIliasWebCrawler
from .logging import log
from .utils import fmt_path


class PferdLoadError(Exception):
    pass


class Pferd:
    def __init__(self, config: Config, cli_crawlers: Optional[List[str]], cli_skips: Optional[List[str]]):
        """
        May throw PferdLoadError.
        """

        self._config = config
        self._crawlers_to_run = self._find_crawlers_to_run(config, cli_crawlers, cli_skips)

        self._authenticators: Dict[str, Authenticator] = {}
        self._crawlers: Dict[str, Crawler] = {}

    def _find_config_crawlers(self, config: Config) -> List[str]:
        crawl_sections = []

        for name, section in config.crawl_sections():
            if CrawlerSection(section).skip():
                log.explain(f"Skipping {name!r}")
            else:
                crawl_sections.append(name)

        return crawl_sections

    def _find_cli_crawlers(self, config: Config, cli_crawlers: List[str]) -> List[str]:
        if len(cli_crawlers) != len(set(cli_crawlers)):
            raise PferdLoadError("Some crawlers were selected multiple times")

        crawl_sections = [name for name, _ in config.crawl_sections()]

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

    def _find_crawlers_to_run(
            self,
            config: Config,
            cli_crawlers: Optional[List[str]],
            cli_skips: Optional[List[str]],
    ) -> List[str]:
        log.explain_topic("Deciding which crawlers to run")

        crawlers: List[str]
        if cli_crawlers is None:
            log.explain("No crawlers specified on CLI")
            log.explain("Running crawlers specified in config")
            crawlers = self._find_config_crawlers(config)
        else:
            log.explain("Crawlers specified on CLI")
            crawlers = self._find_cli_crawlers(config, cli_crawlers)

        skips = {f"crawl:{name}" for name in cli_skips} if cli_skips else set()
        for crawler in crawlers:
            if crawler in skips:
                log.explain(f"Skipping crawler {crawler!r}")
        crawlers = [crawler for crawler in crawlers if crawler not in skips]

        return crawlers

    def _load_authenticators(self) -> None:
        for name, section in self._config.auth_sections():
            log.print(f"[bold bright_cyan]Loading[/] {escape(name)}")

            auth_type = AuthSection(section).type()
            authenticator_constructor = AUTHENTICATORS.get(auth_type)
            if authenticator_constructor is None:
                raise ConfigOptionError(name, "type", f"Unknown authenticator type: {auth_type!r}")

            authenticator = authenticator_constructor(name, section, self._config)
            self._authenticators[name] = authenticator

    def _load_crawlers(self) -> None:
        # Cookie sharing
        kit_ilias_web_paths: Dict[Authenticator, List[Path]] = {}

        for name, section in self._config.crawl_sections():
            log.print(f"[bold bright_cyan]Loading[/] {escape(name)}")

            crawl_type = CrawlerSection(section).type()
            crawler_constructor = CRAWLERS.get(crawl_type)
            if crawler_constructor is None:
                raise ConfigOptionError(name, "type", f"Unknown crawler type: {crawl_type!r}")

            crawler = crawler_constructor(name, section, self._config, self._authenticators)
            self._crawlers[name] = crawler

            if self._config.default_section.share_cookies():
                if isinstance(crawler, KitIliasWebCrawler):
                    crawler.share_cookies(kit_ilias_web_paths)

    def debug_transforms(self) -> None:
        for name in self._crawlers_to_run:
            crawler = self._crawlers[name]
            log.print("")
            log.print(f"[bold bright_cyan]Debugging transforms[/] for {escape(name)}")
            crawler.debug_transforms()

    async def run(self, debug_transforms: bool) -> None:
        """
        May throw ConfigOptionError.
        """

        # These two functions must run inside the same event loop as the
        # crawlers, so that any new objects (like Conditions or Futures) can
        # obtain the correct event loop.
        self._load_authenticators()
        self._load_crawlers()

        if debug_transforms:
            log.output_explain = True
            log.output_report = False
            self.debug_transforms()
            return

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

            def fmt_path_link(relative_path: PurePath) -> str:
                # We need to URL-encode the path because it might contain spaces or special characters
                link = crawler.output_dir.resolve(relative_path).absolute().as_uri()
                return f"[link={link}]{fmt_path(relative_path)}[/link]"

            something_changed = False
            for path in sorted(crawler.report.added_files):
                something_changed = True
                log.report(f"  [bold bright_green]Added[/] {fmt_path_link(path)}")
            for path in sorted(crawler.report.changed_files):
                something_changed = True
                log.report(f"  [bold bright_yellow]Changed[/] {fmt_path_link(path)}")
            for path in sorted(crawler.report.deleted_files):
                something_changed = True
                log.report(f"  [bold bright_magenta]Deleted[/] {fmt_path(path)}")
            for path in sorted(crawler.report.not_deleted_files):
                something_changed = True
                log.report_not_deleted(f"  [bold bright_magenta]Not deleted[/] {fmt_path_link(path)}")

            for warning in crawler.report.encountered_warnings:
                something_changed = True
                log.report(f"  [bold bright_red]Warning[/] {warning}")

            for error in crawler.report.encountered_errors:
                something_changed = True
                log.report(f"  [bold bright_red]Error[/] {error}")

            if not something_changed:
                log.report("  Nothing changed")
