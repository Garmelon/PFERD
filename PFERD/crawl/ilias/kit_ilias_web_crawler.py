from typing import Dict, Literal

from ...auth import Authenticator
from ...config import Config
from .ilias_web_crawler import IliasWebCrawler, IliasWebCrawlerSection
from .shibboleth_login import ShibbolethLogin

_ILIAS_URL = "https://ilias.studium.kit.edu"


class KitShibbolethBackgroundLoginSuccessful:
    pass


class KitIliasWebCrawlerSection(IliasWebCrawlerSection):
    def base_url(self) -> str:
        return _ILIAS_URL

    def login(self) -> Literal["shibboleth"]:
        return "shibboleth"


class KitIliasWebCrawler(IliasWebCrawler):
    def __init__(
        self,
        name: str,
        section: KitIliasWebCrawlerSection,
        config: Config,
        authenticators: Dict[str, Authenticator],
    ):
        super().__init__(name, section, config, authenticators)

        self._shibboleth_login = ShibbolethLogin(
            _ILIAS_URL,
            self._auth,
            section.tfa_auth(authenticators),
        )
