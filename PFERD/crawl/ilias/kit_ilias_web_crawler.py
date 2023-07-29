from typing import Any, Dict, Optional, Union

import aiohttp
import yarl
from bs4 import BeautifulSoup

from ...auth import Authenticator, TfaAuthenticator
from ...config import Config
from ...logging import log
from ...utils import soupify
from ..crawler import CrawlError, CrawlWarning
from .async_helpers import _iorepeat
from .ilias_web_crawler import IliasConfig, IliasWebCrawler, IliasWebCrawlerSection

_ILIAS_URL = "https://ilias.studium.kit.edu"


class KitShibbolethBackgroundLoginSuccessful():
    pass


class KitIliasWebCrawlerSection(IliasWebCrawlerSection):
    def conf(self) -> IliasConfig:
        return IliasConfig(
            base_url=_ILIAS_URL,
            client_id="",
        )

    def tfa_auth(self, authenticators: Dict[str, Authenticator]) -> Optional[Authenticator]:
        value: Optional[str] = self.s.get("tfa_auth")
        if value is None:
            return None
        auth = authenticators.get(value)
        if auth is None:
            self.invalid_value("tfa_auth", value, "No such auth section exists")
        return auth


class KitIliasWebCrawler(IliasWebCrawler):
    def __init__(
        self,
        name: str,
        section: KitIliasWebCrawlerSection,
        config: Config,
        authenticators: Dict[str, Authenticator]
    ):
        super().__init__(name, section, config, authenticators)
        self._shibboleth_login = KitShibbolethLogin(
            self._auth,
            section.tfa_auth(authenticators),
        )

    # We repeat this as the login method in shibboleth doesn't handle I/O errors.
    # Shibboleth is quite reliable as well, the repeat is likely not critical here.
    @ _iorepeat(3, "Login", failure_is_error=True)
    async def _authenticate(self) -> None:
        await self._shibboleth_login.login(self.session)


class KitShibbolethLogin:
    """
    Login via KIT's shibboleth system.
    """

    def __init__(self, authenticator: Authenticator, tfa_authenticator: Optional[Authenticator]) -> None:
        self._auth = authenticator
        self._tfa_auth = tfa_authenticator

    async def login(self, sess: aiohttp.ClientSession) -> None:
        """
        Performs the ILIAS Shibboleth authentication dance and saves the login
        cookies it receieves.

        This function should only be called whenever it is detected that you're
        not logged in. The cookies obtained should be good for a few minutes,
        maybe even an hour or two.
        """

        # Equivalent: Click on "Mit KIT-Account anmelden" button in
        # https://ilias.studium.kit.edu/login.php
        url = f"{_ILIAS_URL}/shib_login.php"
        data = {
            "sendLogin": "1",
            "idp_selection": "https://idp.scc.kit.edu/idp/shibboleth",
            "il_target": "",
            "home_organization_selection": "Weiter",
        }
        soup: Union[BeautifulSoup, KitShibbolethBackgroundLoginSuccessful] = await _shib_post(sess, url, data)

        if isinstance(soup, KitShibbolethBackgroundLoginSuccessful):
            return

        # Attempt to login using credentials, if necessary
        while not self._login_successful(soup):
            # Searching the form here so that this fails before asking for
            # credentials rather than after asking.
            form = soup.find("form", {"class": "full content", "method": "post"})
            action = form["action"]

            csrf_token = form.find("input", {"name": "csrf_token"})["value"]

            # Equivalent: Enter credentials in
            # https://idp.scc.kit.edu/idp/profile/SAML2/Redirect/SSO
            url = "https://idp.scc.kit.edu" + action
            username, password = await self._auth.credentials()
            data = {
                "_eventId_proceed": "",
                "j_username": username,
                "j_password": password,
                "csrf_token": csrf_token
            }
            soup = await _post(sess, url, data)

            if soup.find(id="attributeRelease"):
                raise CrawlError(
                    "ILIAS Shibboleth entitlements changed! "
                    "Please log in once in your browser and review them"
                )

            if self._tfa_required(soup):
                soup = await self._authenticate_tfa(sess, soup)

            if not self._login_successful(soup):
                self._auth.invalidate_credentials()

        # Equivalent: Being redirected via JS automatically
        # (or clicking "Continue" if you have JS disabled)
        relay_state = soup.find("input", {"name": "RelayState"})
        saml_response = soup.find("input", {"name": "SAMLResponse"})
        url = f"{_ILIAS_URL}/Shibboleth.sso/SAML2/POST"
        data = {  # using the info obtained in the while loop above
            "RelayState": relay_state["value"],
            "SAMLResponse": saml_response["value"],
        }
        await sess.post(url, data=data)

    async def _authenticate_tfa(
            self,
            session: aiohttp.ClientSession,
            soup: BeautifulSoup
    ) -> BeautifulSoup:
        if not self._tfa_auth:
            self._tfa_auth = TfaAuthenticator("ilias-anon-tfa")

        tfa_token = await self._tfa_auth.password()

        # Searching the form here so that this fails before asking for
        # credentials rather than after asking.
        form = soup.find("form", {"method": "post"})
        action = form["action"]
        csrf_token = form.find("input", {"name": "csrf_token"})["value"]

        # Equivalent: Enter token in
        # https://idp.scc.kit.edu/idp/profile/SAML2/Redirect/SSO
        url = "https://idp.scc.kit.edu" + action
        data = {
            "_eventId_proceed": "",
            "j_tokenNumber": tfa_token,
            "csrf_token": csrf_token
        }
        return await _post(session, url, data)

    @staticmethod
    def _login_successful(soup: BeautifulSoup) -> bool:
        relay_state = soup.find("input", {"name": "RelayState"})
        saml_response = soup.find("input", {"name": "SAMLResponse"})
        return relay_state is not None and saml_response is not None

    @staticmethod
    def _tfa_required(soup: BeautifulSoup) -> bool:
        return soup.find(id="j_tokenNumber") is not None


async def _post(session: aiohttp.ClientSession, url: str, data: Any) -> BeautifulSoup:
    async with session.post(url, data=data) as response:
        return soupify(await response.read())


async def _shib_post(
    session: aiohttp.ClientSession,
    url: str,
    data: Any
) -> Union[BeautifulSoup, KitShibbolethBackgroundLoginSuccessful]:
    """
    aiohttp unescapes '/' and ':' in URL query parameters which is not RFC compliant and rejected
    by Shibboleth. Thanks a lot. So now we unroll the requests manually, parse location headers and
    build encoded URL objects ourselves... Who thought mangling location header was a good idea??
    """
    log.explain_topic("Shib login POST")
    async with session.post(url, data=data, allow_redirects=False) as response:
        location = response.headers.get("location")
        log.explain(f"Got location {location!r}")
        if not location:
            raise CrawlWarning(f"Login failed (1), no location header present at {url}")
        correct_url = yarl.URL(location, encoded=True)
        log.explain(f"Corrected location to {correct_url!r}")

        if str(correct_url).startswith(_ILIAS_URL):
            log.explain("ILIAS recognized our shib token and logged us in in the background, returning")
            return KitShibbolethBackgroundLoginSuccessful()

        async with session.get(correct_url, allow_redirects=False) as response:
            location = response.headers.get("location")
            log.explain(f"Redirected to {location!r} with status {response.status}")
            # If shib still still has a valid session, it will directly respond to the request
            if location is None:
                log.explain("Shib recognized us, returning its response directly")
                return soupify(await response.read())

            as_yarl = yarl.URL(response.url)
            # Probably not needed anymore, but might catch a few weird situations with a nicer message
            if not location or not as_yarl.host:
                raise CrawlWarning(f"Login failed (2), no location header present at {correct_url}")

            correct_url = yarl.URL.build(
                scheme=as_yarl.scheme,
                host=as_yarl.host,
                path=location,
                encoded=True
            )
            log.explain(f"Corrected location to {correct_url!r}")

            async with session.get(correct_url, allow_redirects=False) as response:
                return soupify(await response.read())
