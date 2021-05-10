from configparser import SectionProxy
from typing import Callable, Dict

from ..config import Config
from ..crawler import Crawler, CrawlerSection
from .local import LocalCrawler, LocalCrawlerSection

CRAWLERS: Dict[str, Callable[[str, Config, SectionProxy], Crawler]] = {
    "local": lambda n, c, s: LocalCrawler(n, c, LocalCrawlerSection(s)),
}
