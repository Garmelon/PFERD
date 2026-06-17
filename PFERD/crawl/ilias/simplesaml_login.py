from typing import Any, Optional, cast

import aiohttp
import yarl
from bs4 import BeautifulSoup, Tag

from ...auth import Authenticator, TfaAuthenticator
from ...logging import log
from ...utils import soupify
from ..crawler import CrawlError


class SimpleSAMLLogin:
    """
    Login via a SimpleSAML system.

    It performs a basic authentication by following the login redirect
    and posting credentials to the indicated form. It also supports TFA similar to Shibboleth.
    """

    def __init__(
        self, ilias_url: str, authenticator: Authenticator, tfa_authenticator: Optional[Authenticator]
    ) -> None:
        self._ilias_url = ilias_url
        self._auth = authenticator
        self._tfa_auth = tfa_authenticator

    async def login(self, sess: aiohttp.ClientSession) -> None:
        """
        Perform a SimpleSAML login flow and populate the session cookies.
        """

        # Start at the local login entrypoint which may redirect to SimpleSAML
        url = f"{self._ilias_url}/saml.php"
        async with sess.get(url) as response:
            saml_url = response.url
            # If the redirect stayed on the ILIAS host, assume we're already logged in
            if str(saml_url).startswith(self._ilias_url):
                log.explain("ILIAS recognized our SAML token and logged us in in the background, returning")
                return
            soup: BeautifulSoup = soupify(await response.read())

        # The SimpleSAML login page uses a form POST similar to Shibboleth.
        # Attempt to login using credentials.
        while not self._login_successful(soup):
            form = cast(Tag, soup.find("form", {"method": "post"}))
            action = cast(str, form["action"])
            # dynamically determine full URL from action (FAU uses full URL here, KIT uses relative URL)
            url = action if action.startswith("https") else str(saml_url.origin()) + action

            username, password = await self._auth.credentials()
            data = {
                "username": username,
                "password": password,
            }
            if csrf_token_input := form.find("input", {"name": "csrf_token"}):
                data["csrf_token"] = csrf_token_input["value"]  # type: ignore

            soup = await _post(sess, url, data)

            # Detect attribute release prompt
            if soup.find(id="attributeRelease"):
                raise CrawlError(
                    "ILIAS SAML entitlements changed! Please log in once in your browser and review them"
                )

            if self._tfa_required(soup):
                soup = await self._authenticate_tfa(sess, soup, saml_url)

            if not self._login_successful(soup):
                self._auth.invalidate_credentials()

        # Equivalent: Being redirected via JS automatically
        # (or clicking "Continue" if you have JS disabled)
        relay_state = cast(Tag, soup.find("input", {"name": "RelayState"}))
        saml_response = cast(Tag, soup.find("input", {"name": "SAMLResponse"}))
        url = cast(str, cast(Tag, soup.find("form", {"method": "post"}))["action"])
        data = {  # using the info obtained in the while loop above
            "RelayState": cast(str, relay_state["value"]),
            "SAMLResponse": cast(str, saml_response["value"]),
        }
        await sess.post(cast(str, url), data=data)

    async def _authenticate_tfa(
        self, session: aiohttp.ClientSession, soup: BeautifulSoup, saml_url: yarl.URL
    ) -> BeautifulSoup:
        if not self._tfa_auth:
            self._tfa_auth = TfaAuthenticator("ilias-anon-tfa")

        tfa_token = await self._tfa_auth.password()

        # Searching the form here so that this fails before asking for
        # credentials rather than after asking.
        form = cast(Tag, soup.find("form", {"method": "post"}))
        action = cast(str, form["action"])
        # dynamically determine full URL from action (FAU uses full URL here, KIT uses relative URL)
        url = action if action.startswith("https") else str(saml_url.origin()) + action

        data = {  # for www.sso.uni-erlangen.de/simplesaml/module.php/mfa/otp?...
            "otp": tfa_token
        }
        if csrf_token_input := form.find("input", {"name": "csrf_token"}):
            data["csrf_token"] = csrf_token_input["value"]  # type: ignore
        return await _post(session, url, data)

    @staticmethod
    def _login_successful(soup: BeautifulSoup) -> bool:
        relay_state = soup.find("input", {"name": "RelayState"})
        saml_response = soup.find("input", {"name": "SAMLResponse"})
        return relay_state is not None and saml_response is not None

    @staticmethod
    def _tfa_required(soup: BeautifulSoup) -> bool:
        # Also treat a body with id="mfa:otp" as TFA required (for FAU)
        body = soup.find("body")
        return body is not None and body.get("id") == "mfa:otp"


async def _post(session: aiohttp.ClientSession, url: str, data: Any) -> BeautifulSoup:
    async with session.post(url, data=data) as response:
        return soupify(await response.read())
