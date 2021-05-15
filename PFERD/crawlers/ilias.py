from configparser import SectionProxy
from pathlib import PurePath
from typing import Any, Dict, Optional

import aiohttp
from bs4 import BeautifulSoup
from PFERD.utils import soupify

from ..authenticators import Authenticator
from ..conductor import TerminalConductor
from ..config import Config
from ..crawler import (Crawler, CrawlerSection, HttpCrawler, anoncritical,
                       arepeat)


class IliasCrawlerSection(CrawlerSection):

    def __init__(self, section: SectionProxy):
        super().__init__(section)

        if not self.course_id() and not self.element_url():
            self.missing_value("course_id or element_url")

    def course_id(self) -> Optional[str]:
        return self.s.get("course_id")

    def element_url(self) -> Optional[str]:
        return self.s.get("element_url")

    def base_url(self) -> str:
        return self.s.get("ilias_url", "https://ilias.studium.kit.edu/")

    def tfa_auth(self, authenticators: Dict[str, Authenticator]) -> Optional[Authenticator]:
        value = self.s.get("tfa_auth")
        if not value:
            return None

        auth = authenticators.get(f"auth:{value}")
        if auth is None:
            self.invalid_value("auth", value, "No such auth section exists")
        return auth


class IliasCrawler(HttpCrawler):
    def __init__(
            self,
            name: str,
            section: IliasCrawlerSection,
            config: Config,
            conductor: TerminalConductor,
            authenticators: Dict[str, Authenticator]
    ):
        super().__init__(name, section, config, conductor)

        self._shibboleth_login = KitShibbolethLogin(
            section.auth(authenticators),
            section.tfa_auth(authenticators)
        )
        self._base_url = section.base_url()

        self._course_id = section.course_id()
        self._element_url = section.element_url()

    async def crawl(self) -> None:
        async with self.crawl_bar(PurePath("/")) as bar:
            soup = await self._get_page(self._base_url)
            self.print("[green]Gotcha![/]")

    async def _get_page(self, url: str, retries_left: int = 3) -> BeautifulSoup:
        if retries_left < 0:
            # TODO: Proper exception
            raise RuntimeError("Get page failed too often")
        async with self.session.get(url) as request:
            soup = soupify(await request.read())
            if self._is_logged_in(soup):
                return soup

        await self._shibboleth_login.login(self.session)

        return await self._get_page(url, retries_left - 1)

    @staticmethod
    def _is_logged_in(soup: BeautifulSoup) -> bool:
        # Normal ILIAS pages
        userlog = soup.find("li", {"id": "userlog"})
        if userlog is not None:
            return True
        # Video listing embeds do not have complete ILIAS html. Try to match them by
        # their video listing table
        video_table = soup.find(
            recursive=True,
            name="table",
            attrs={"id": lambda x: x is not None and x.startswith("tbl_xoct")}
        )
        if video_table is not None:
            return True
        # The individual video player wrapper page has nothing of the above.
        # Match it by its playerContainer.
        if soup.select_one("#playerContainer") is not None:
            return True
        return False


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
        url = "https://ilias.studium.kit.edu/Shibboleth.sso/Login"
        data = {
            "sendLogin": "1",
            "idp_selection": "https://idp.scc.kit.edu/idp/shibboleth",
            "target": "/shib_login.php",
            "home_organization_selection": "Mit KIT-Account anmelden",
        }
        soup: BeautifulSoup = await _post(sess, url, data)

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

            if self._tfa_required(soup):
                soup = await self._authenticate_tfa(sess, soup)

            if not self._login_successful(soup):
                self._auth.invalid_credentials()

        # Equivalent: Being redirected via JS automatically
        # (or clicking "Continue" if you have JS disabled)
        relay_state = soup.find("input", {"name": "RelayState"})
        saml_response = soup.find("input", {"name": "SAMLResponse"})
        url = "https://ilias.studium.kit.edu/Shibboleth.sso/SAML2/POST"
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
            raise RuntimeError("No 'tfa_auth' present but you use two-factor authentication!")

        _, tfa_token = await self._tfa_auth.credentials()

        # Searching the form here so that this fails before asking for
        # credentials rather than after asking.
        form = soup.find("form", {"method": "post"})
        action = form["action"]

        # Equivalent: Enter token in
        # https://idp.scc.kit.edu/idp/profile/SAML2/Redirect/SSO
        url = "https://idp.scc.kit.edu" + action
        data = {
            "_eventId_proceed": "",
            "j_tokenNumber": tfa_token
        }
        return _post(session, url, data)

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
