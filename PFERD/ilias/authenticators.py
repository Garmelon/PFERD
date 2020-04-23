"""
Authenticators that can obtain proper ILIAS session cookies.
"""

import abc
import logging
from typing import Optional

import bs4
import requests

from ..authenticators import UserPassAuthenticator
from ..utils import soupify

LOGGER = logging.getLogger(__name__)


# TODO save cookies whenever we know they're good


class IliasAuthenticator(abc.ABC):
    # pylint: disable=too-few-public-methods

    """
    An authenticator that logs an existing requests session into an ILIAS
    account.
    """

    @abc.abstractmethod
    def authenticate(self, sess: requests.Session) -> None:
        """
        Log a requests session into this authenticator's ILIAS account.
        """


class KitShibbolethAuthenticator(IliasAuthenticator):
    # pylint: disable=too-few-public-methods

    """
    Authenticate via KIT's shibboleth system.
    """

    def __init__(self, username: Optional[str] = None, password: Optional[str] = None) -> None:
        self._auth = UserPassAuthenticator("KIT ILIAS Shibboleth", username, password)

    def authenticate(self, sess: requests.Session) -> None:
        """
        Performs the ILIAS Shibboleth authentication dance and saves the login
        cookies it receieves.

        This function should only be called whenever it is detected that you're
        not logged in. The cookies obtained should be good for a few minutes,
        maybe even an hour or two.
        """

        # Equivalent: Click on "Mit KIT-Account anmelden" button in
        # https://ilias.studium.kit.edu/login.php
        LOGGER.debug("Begin authentication process with ILIAS")
        url = "https://ilias.studium.kit.edu/Shibboleth.sso/Login"
        data = {
            "sendLogin": "1",
            "idp_selection": "https://idp.scc.kit.edu/idp/shibboleth",
            "target": "/shib_login.php",
            "home_organization_selection": "Mit KIT-Account anmelden",
        }
        soup = soupify(sess.post(url, data=data))

        # Attempt to login using credentials, if necessary
        while not self._login_successful(soup):
            # Searching the form here so that this fails before asking for
            # credentials rather than after asking.
            form = soup.find("form", {"class": "form2", "method": "post"})
            action = form["action"]

            # Equivalent: Enter credentials in
            # https://idp.scc.kit.edu/idp/profile/SAML2/Redirect/SSO
            LOGGER.debug("Attempt to log in to Shibboleth using credentials")
            url = "https://idp.scc.kit.edu" + action
            data = {
                "_eventId_proceed": "",
                "j_username": self._auth.username,
                "j_password": self._auth.password,
            }
            soup = soupify(sess.post(url, data=data))

            if not self._login_successful(soup):
                print("Incorrect credentials.")
                self._auth.invalidate_credentials()

        # Equivalent: Being redirected via JS automatically
        # (or clicking "Continue" if you have JS disabled)
        LOGGER.debug("Redirect back to ILIAS with login information")
        relay_state = soup.find("input", {"name": "RelayState"})
        saml_response = soup.find("input", {"name": "SAMLResponse"})
        url = "https://ilias.studium.kit.edu/Shibboleth.sso/SAML2/POST"
        data = {  # using the info obtained in the while loop above
            "RelayState": relay_state["value"],
            "SAMLResponse": saml_response["value"],
        }
        sess.post(url, data=data)

    @staticmethod
    def _login_successful(soup: bs4.BeautifulSoup) -> bool:
        relay_state = soup.find("input", {"name": "RelayState"})
        saml_response = soup.find("input", {"name": "SAMLResponse"})
        return relay_state is not None and saml_response is not None
