from configparser import SectionProxy
from typing import Callable, Dict

from ..auth import Authenticator
from ..config import Config
from .crawler import Crawler, CrawlError, CrawlerSection  # noqa: F401
from .ilias import IliasWebCrawler, IliasWebCrawlerSection, KitIliasWebCrawler, KitIliasWebCrawlerSection
from .kit_ipd_crawler import KitIpdCrawler, KitIpdCrawlerSection
from .local_crawler import LocalCrawler, LocalCrawlerSection

CrawlerConstructor = Callable[[
    str,                       # Name (without the "crawl:" prefix)
    SectionProxy,              # Crawler's section of global config
    Config,                    # Global config
    Dict[str, Authenticator],  # Loaded authenticators by name
], Crawler]

CRAWLERS: Dict[str, CrawlerConstructor] = {
    "local": lambda n, s, c, a:
        LocalCrawler(n, LocalCrawlerSection(s), c),
    "ilias-web": lambda n, s, c, a:
        IliasWebCrawler(n, IliasWebCrawlerSection(s), c, a),
    "kit-ilias-web": lambda n, s, c, a:
        KitIliasWebCrawler(n, KitIliasWebCrawlerSection(s), c, a),
    "kit-ipd": lambda n, s, c, a:
        KitIpdCrawler(n, KitIpdCrawlerSection(s), c),
}
