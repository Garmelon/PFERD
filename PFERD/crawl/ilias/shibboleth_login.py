from typing import Any, Optional, cast

import aiohttp
import yarl
from bs4 import BeautifulSoup, Tag

from ...auth import Authenticator, TfaAuthenticator
from ...logging import log
from ...utils import soupify
from ..crawler import CrawlError


class ShibbolethLogin:
    """
    Login via shibboleth system.
    """

    def __init__(
        self, ilias_url: str, authenticator: Authenticator, tfa_authenticator: Optional[Authenticator]
    ) -> None:
        self._ilias_url = ilias_url
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
        url = f"{self._ilias_url}/shib_login.php"
        async with sess.get(url) as response:
            shib_url = response.url
            if str(shib_url).startswith(self._ilias_url):
                log.explain(
                    "ILIAS recognized our shib token and logged us in in the background, returning"
                )
                return
            soup: BeautifulSoup = soupify(await response.read())

        # Attempt to login using credentials, if necessary
        while not self._login_successful(soup):
            # Searching the form here so that this fails before asking for
            # credentials rather than after asking.
            form = cast(Tag, soup.find("form", {"method": "post"}))
            action = cast(str, form["action"])

            # Equivalent: Enter credentials in
            # https://idp.scc.kit.edu/idp/profile/SAML2/Redirect/SSO
            url = str(shib_url.origin()) + action
            username, password = await self._auth.credentials()
            data = {
                "_eventId_proceed": "",
                "j_username": username,
                "j_password": password,
                "fudis_web_authn_assertion_input": "",
            }
            if csrf_token_input := form.find("input", {"name": "csrf_token"}):
                data["csrf_token"] = csrf_token_input["value"]  # type: ignore
            soup = await _post(sess, url, data)

            if soup.find(id="attributeRelease"):
                raise CrawlError(
                    "ILIAS Shibboleth entitlements changed! "
                    "Please log in once in your browser and review them"
                )

            if self._tfa_required(soup):
                soup = await self._authenticate_tfa(sess, soup, shib_url)

            if not self._login_successful(soup):
                self._auth.invalidate_credentials()

        # Equivalent: Being redirected via JS automatically
        # (or clicking "Continue" if you have JS disabled)
        relay_state = cast(Tag, soup.find("input", {"name": "RelayState"}))
        saml_response = cast(Tag, soup.find("input", {"name": "SAMLResponse"}))
        url = form = soup.find("form", {"method": "post"})["action"]  # type: ignore
        data = {  # using the info obtained in the while loop above
            "RelayState": cast(str, relay_state["value"]),
            "SAMLResponse": cast(str, saml_response["value"]),
        }
        await sess.post(cast(str, url), data=data)

    async def _authenticate_tfa(
        self, session: aiohttp.ClientSession, soup: BeautifulSoup, shib_url: yarl.URL
    ) -> BeautifulSoup:
        if not self._tfa_auth:
            self._tfa_auth = TfaAuthenticator("ilias-anon-tfa")

        tfa_token = await self._tfa_auth.password()

        # Searching the form here so that this fails before asking for
        # credentials rather than after asking.
        form = cast(Tag, soup.find("form", {"method": "post"}))
        action = cast(str, form["action"])

        # Equivalent: Enter token in
        # https://idp.scc.kit.edu/idp/profile/SAML2/Redirect/SSO
        url = str(shib_url.origin()) + action
        username, password = await self._auth.credentials()
        data = {
            "_eventId_proceed": "",
            "fudis_otp_input": tfa_token,
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
        return soup.find(id="fudiscr-form") is not None


async def _post(session: aiohttp.ClientSession, url: str, data: Any) -> BeautifulSoup:
    async with session.post(url, data=data) as response:
        return soupify(await response.read())
