from configparser import SectionProxy
from typing import Callable, Dict

from ..conductor import TerminalConductor
from ..config import Config
from ..crawler import Crawler
from .local import LocalCrawler, LocalCrawlerSection

CrawlerConstructor = Callable[[
    str,                # Name (without the "crawl:" prefix)
    SectionProxy,       # Crawler's section of global config
    Config,             # Global config
    TerminalConductor,  # Global conductor instance
], Crawler]

CRAWLERS: Dict[str, CrawlerConstructor] = {
    "local": lambda n, s, c, t:
        LocalCrawler(n, LocalCrawlerSection(s), c, t),
}
