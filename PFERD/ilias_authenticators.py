# This file is called IliasAuthenticators because there are multiple mechanisms
# for authenticating with Ilias (even though only the Shibboleth is currently
# implemented). Most of what the ShibbolethAuthenticator currently does is
# not Shibboleth specific; this mess would have to be cleaned up before
# actually implementing any other authentication method.
#
# I think the only other method is the password prompt when clicking the log in
# button.

import getpass
import http.cookiejar
import logging
import time

import bs4
import requests

from .utils import ContentTypeException, stream_to_path

__all__ = ["ShibbolethAuthenticator"]
logger = logging.getLogger(__name__)

class ShibbolethAuthenticator:
    ILIAS_GOTO = "https://ilias.studium.kit.edu/goto.php"

    def __init__(self, cookie_file) -> None:
        # Because LWPCookieJar insists on the path being str-like instead of
        # Path-like.
        cookie_file = str(cookie_file)

        cookies = http.cookiejar.LWPCookieJar(cookie_file)
        try:
            logger.info(f"Loading old cookies from {cookie_file!r}")
            cookies.load(ignore_discard=True)
        except (FileNotFoundError, http.cookiejar.LoadError):
            logger.warn(f"No (valid) cookie file found at {cookie_file!r}, ignoring...")

        self._session = requests.Session()
        self._session.cookies = cookies

    def _authenticate(self):
        """
        Performs the ILIAS Shibboleth authentication dance and saves the login
        cookies it receieves.

        This function should only be called whenever it is detected that you're
        not logged in. The cookies obtained should be good for a few minutes,
        maybe even an hour or two.
        """

        # Equivalent: Click on "Mit KIT-Account anmelden" button in
        # https://ilias.studium.kit.edu/login.php
        logger.debug("Begin authentication process with ILIAS")
        url = "https://ilias.studium.kit.edu/Shibboleth.sso/Login"
        data = {
                "sendLogin": "1",
                "idp_selection": "https://idp.scc.kit.edu/idp/shibboleth",
                "target": "/shib_login.php",
                "home_organization_selection": "Mit KIT-Account anmelden",
        }
        r = self._session.post(url, data=data)
        soup = bs4.BeautifulSoup(r.text, "html.parser")

        # Attempt to login using credentials, if necessary
        while not self._login_successful(soup):
            # Searching the form here so that this fails before asking for
            # credentials rather than after asking.
            form = soup.find("form", {"class": "form2", "method": "post"})
            action = form["action"]

            print("Please enter Shibboleth credentials.")
            username = getpass.getpass(prompt="Username: ")
            password = getpass.getpass(prompt="Password: ")

            # Equivalent: Enter credentials in
            # https://idp.scc.kit.edu/idp/profile/SAML2/Redirect/SSO
            logger.debug("Attempt to log in to Shibboleth using credentials")
            url = "https://idp.scc.kit.edu" + action
            data = {
                    "_eventId_proceed": "",
                    "j_username": username,
                    "j_password": password,
            }
            r = self._session.post(url, data=data)
            soup = bs4.BeautifulSoup(r.text, "html.parser")

            if not self._login_successful(soup):
                print("Incorrect credentials.")

        # Saving progress
        logger.info("Saving cookies (successfully authenticated with Shibboleth)")
        self._session.cookies.save(ignore_discard=True)

        # Equivalent: Being redirected via JS automatically
        # (or clicking "Continue" if you have JS disabled)
        logger.debug("Redirect back to ILIAS with login information")
        relay_state = soup.find("input", {"name": "RelayState"})
        saml_response = soup.find("input", {"name": "SAMLResponse"})
        url = "https://ilias.studium.kit.edu/Shibboleth.sso/SAML2/POST"
        data = { # using the info obtained in the while loop above
            "RelayState": relay_state["value"],
            "SAMLResponse": saml_response["value"],
        }
        self._session.post(url, data=data)

        # Saving progress
        logger.info("Saving cookies (successfully authenticated with ILIAS)")
        self._session.cookies.save(ignore_discard=True)

    def _login_successful(self, soup):
        relay_state = soup.find("input", {"name": "RelayState"})
        saml_response = soup.find("input", {"name": "SAMLResponse"})
        return relay_state is not None and saml_response is not None

    def _is_logged_in(self, soup):
        userlog = soup.find("li", {"id": "userlog"})
        return userlog is not None

    def get_webpage(self, object_id):
        params = {"target": object_id}

        while True:
            logger.debug(f"Getting {self.ILIAS_GOTO} {params}")
            r = self._session.get(self.ILIAS_GOTO, params=params)
            soup = bs4.BeautifulSoup(r.text, "html.parser")

            if self._is_logged_in(soup):
                return soup
            else:
                logger.info("Not logged in, authenticating...")
                self._authenticate()

    def get_webpage_by_refid(self, ref_id):
        return self.get_webpage(f"fold_{ref_id}")

    def _download(self, url, params, to_path):
        with self._session.get(url, params=params, stream=True) as r:
            content_type = r.headers["content-type"]

            if content_type.startswith("text/html"):
                # Dangit, we're probably not logged in.
                soup = bs4.BeautifulSoup(r.text, "html.parser")
                if self._is_logged_in(soup):
                    raise ContentTypeException(
                            "Attempting to download a web page, not a file")
                return False
            else:
                # Yay, we got the file :)
                stream_to_path(r, to_path)
                return True

    def download_file(self, file_id, to_path):
        params = {"target": file_id}

        while True:
            success = self._download(self.ILIAS_GOTO, params, to_path)

            if success:
                return
            else:
                logger.info("Not logged in, authenticating...")
                self._authenticate()
