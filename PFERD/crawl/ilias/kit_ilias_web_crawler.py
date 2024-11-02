from typing import Dict, Union

from ...auth import Authenticator
from ...config import Config
from .async_helper import _iorepeat
from .ilias_web_crawler import IliasWebCrawler, IliasWebCrawlerSection, ShibbolethLoginType
from .shibboleth_login import ShibbolethLogin

TargetType = Union[str, int]

# _ILIAS_URL = "https://ilias.studium.kit.edu"
_ILIAS_URL = "https://ovidius.uni-tuebingen.de/ilias3"


class KitShibbolethBackgroundLoginSuccessful:
    pass


class KitIliasWebCrawlerSection(IliasWebCrawlerSection):
    def base_url(self) -> str:
        return _ILIAS_URL

    def login(self) -> ShibbolethLoginType:
        return ShibbolethLoginType()


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
