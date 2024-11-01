from typing import Any, Dict, Optional, Union

import aiohttp
import yarl
from bs4 import BeautifulSoup

from ...auth import Authenticator, TfaAuthenticator
from ...config import Config
from ...logging import log
from ...utils import soupify
from ..crawler import CrawlError, CrawlWarning
from .async_helper import _iorepeat
from .ilias_web_crawler import IliasWebCrawler, IliasWebCrawlerSection
from .shibboleth_login import ShibbolethLogin

TargetType = Union[str, int]

_ILIAS_URL = "https://ilias.studium.kit.edu"


class KitShibbolethBackgroundLoginSuccessful:
    pass


class KitIliasWebCrawlerSection(IliasWebCrawlerSection):
    def base_url(self) -> str:
        return _ILIAS_URL

    def client_id(self) -> str:
        # KIT ILIAS uses the Shibboleth service for authentication. There's no
        # use for a client id.
        return "unused"

    def tfa_auth(
        self, authenticators: Dict[str, Authenticator]
    ) -> Optional[Authenticator]:
        value: Optional[str] = self.s.get("tfa_auth")
        if value is None:
            return None
        auth = authenticators.get(value)
        if auth is None:
            self.invalid_value("tfa_auth", value,
                               "No such auth section exists")
        return auth


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

    # We repeat this as the login method in shibboleth doesn't handle I/O errors.
    # Shibboleth is quite reliable as well, the repeat is likely not critical here.
    @_iorepeat(3, "Login", failure_is_error=True)
    async def _authenticate(self) -> None:
        await self._shibboleth_login.login(self.session)
