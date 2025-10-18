from typing import Dict, Literal

from ...auth import Authenticator
from ...config import Config
from .ilias_web_crawler import IliasWebCrawler, IliasWebCrawlerSection
from .fau_shibboleth_login import FauShibbolethLogin

_ILIAS_URL = "https://www.studon.fau.de/studon"

class KitShibbolethBackgroundLoginSuccessful:
    pass

class FauIliasWebCrawlerSection(IliasWebCrawlerSection):
    def base_url(self) -> str:
        return _ILIAS_URL

    def login(self) -> Literal["shibboleth"]:
        return "shibboleth"


class FauIliasWebCrawler(IliasWebCrawler):
    def __init__(
        self,
        name: str,
        section: FauIliasWebCrawlerSection,
        config: Config,
        authenticators: Dict[str, Authenticator],
    ):
        super().__init__(name, section, config, authenticators)

        self._shibboleth_login = FauShibbolethLogin(
            _ILIAS_URL,
            self._auth,
            section.tfa_auth(authenticators),
        )
