from configparser import SectionProxy
from typing import Callable, Dict

from ..authenticator import Authenticator
from ..conductor import TerminalConductor
from ..config import Config
from ..crawler import Crawler
from .ilias import IliasCrawler, IliasCrawlerSection
from .local import LocalCrawler, LocalCrawlerSection

CrawlerConstructor = Callable[[
    str,                       # Name (without the "crawl:" prefix)
    SectionProxy,              # Crawler's section of global config
    Config,                    # Global config
    TerminalConductor,         # Global conductor instance
    Dict[str, Authenticator],  # Loaded authenticators by name
], Crawler]

CRAWLERS: Dict[str, CrawlerConstructor] = {
    "local": lambda n, s, c, t, a:
        LocalCrawler(n, LocalCrawlerSection(s), c, t),
    "ilias": lambda n, s, c, t, a:
        IliasCrawler(n, IliasCrawlerSection(s), c, t, a),
}
