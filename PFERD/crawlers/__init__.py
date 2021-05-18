from configparser import SectionProxy
from typing import Callable, Dict

from ..authenticator import Authenticator
from ..config import Config
from ..crawler import Crawler
from .ilias import KitIliasCrawler, KitIliasCrawlerSection
from .local import LocalCrawler, LocalCrawlerSection

CrawlerConstructor = Callable[[
    str,                       # Name (without the "crawl:" prefix)
    SectionProxy,              # Crawler's section of global config
    Config,                    # Global config
    Dict[str, Authenticator],  # Loaded authenticators by name
], Crawler]

CRAWLERS: Dict[str, CrawlerConstructor] = {
    "local": lambda n, s, c, a:
        LocalCrawler(n, LocalCrawlerSection(s), c),
    "kit-ilias": lambda n, s, c, a:
        KitIliasCrawler(n, KitIliasCrawlerSection(s), c, a),
}
