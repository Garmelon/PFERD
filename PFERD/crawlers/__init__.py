from configparser import SectionProxy
from typing import Callable, Dict

from ..config import Config
from ..crawler import Crawler, CrawlerSection
from .dummy import DummyCrawler
from .local import LocalCrawler, LocalCrawlerSection

CRAWLERS: Dict[str, Callable[[str, Config, SectionProxy], Crawler]] = {
    "dummy": lambda n, c, s: DummyCrawler(n, c, CrawlerSection(s)),
    "local": lambda n, c, s: LocalCrawler(n, c, LocalCrawlerSection(s)),
}
