from dataclasses import dataclass
from typing import Any, Optional, cast
from urllib.parse import urljoin

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
                log.explain("ILIAS recognized our shib token and logged us in in the background, returning")
                return
            soup: BeautifulSoup = soupify(await response.read())

        # Attempt to login using credentials, if necessary
        page_url = str(shib_url)
        while not self._login_successful(soup):
            if soup.find(id="attributeRelease"):
                raise CrawlError(
                    "ILIAS Shibboleth entitlements changed! "
                    "Please log in once in your browser and review them"
                )

            # Searching the form here so that this fails before asking for
            # credentials rather than after asking.
            form = soup.find("form", {"method": "post"})
            if not isinstance(form, Tag):
                raise CrawlError(f"Unexpected Shibboleth page without login form at {page_url!r}")
            url = urljoin(page_url, cast(Optional[str], form.get("action")) or page_url)
            inputs = _form_inputs(form)
            user_field = next((name for name in _LOGIN_FORMS if name in inputs), None)

            if user_field:
                # Equivalent: Enter credentials in
                # https://idp.scc.kit.edu/idp/profile/SAML2/Redirect/SSO or
                # https://mylogin.ub.uni-freiburg.de/authn/login (Uni Freiburg)
                username, password = await self._auth.credentials()
                soup, page_url = await _post(sess, url, _login_data(user_field, inputs, username, password))

                if soup.find("input", {"name": user_field}):
                    log.warn(f"Shibboleth login failed: {_login_error(soup)}")
                    self._auth.invalidate_credentials()
            elif self._tfa_required(soup):
                # Also asks for a new token if the previous one was wrong
                soup, page_url = await self._authenticate_tfa(sess, soup, shib_url)
            elif _is_local_storage_page(inputs):
                # Equivalent: Being redirected via JS automatically by the
                # Shibboleth IdP's local storage check
                soup, page_url = await _post(sess, url, inputs)
            else:
                raise CrawlError(f"Unexpected Shibboleth page at {page_url!r} (inputs: {', '.join(inputs)})")

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
        self, session: aiohttp.ClientSession, soup: BeautifulSoup, shib_url: yarl.URL
    ) -> tuple[BeautifulSoup, str]:
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


@dataclass(frozen=True)
class _LoginForm:
    password_field: str
    # Submit button we click, with its value
    submit_fields: dict[str, str]
    # Sent with the form's value, if the form has them
    copied_fields: tuple[str, ...] = ()


# Known login forms, by their username field. Only these fields are sent.
_LOGIN_FORMS = {
    # Shibboleth IdP default login page (KIT and others)
    "j_username": _LoginForm(
        password_field="j_password",
        submit_fields={"_eventId_proceed": ""},
        copied_fields=("csrf_token", "fudis_web_authn_assertion_input"),  # The latter only at KIT
    ),
    # Uni Freiburg
    "LoginForm[username]": _LoginForm(
        password_field="LoginForm[password]",
        submit_fields={"yt0": "Login"},
        copied_fields=("LoginForm[context]",),
    ),
}

# Fields of the Shibboleth IdP's local storage pages (client-storage/read.vm and write.vm)
_LOCAL_STORAGE_FIELDS = {
    "csrf_token",
    "_eventId_proceed",
    "shib_idp_ls_supported",
    *(
        f"shib_idp_ls_{kind}.{key}"
        for kind in ("exception", "success", "value")
        for key in ("shib_idp_session_ss", "shib_idp_persistent_ss")
    ),
}


def _is_local_storage_page(inputs: dict[str, str]) -> bool:
    # Only known fields, so we never confirm some other IdP prompt
    return inputs.keys() <= _LOCAL_STORAGE_FIELDS and any(name.startswith("shib_idp_ls_") for name in inputs)


def _login_data(user_field: str, inputs: dict[str, str], username: str, password: str) -> dict[str, str]:
    form = _LOGIN_FORMS[user_field]
    return {
        **form.submit_fields,
        **{name: inputs[name] for name in form.copied_fields if name in inputs},
        user_field: username,
        form.password_field: password,
    }


def _form_inputs(form: Tag) -> dict[str, str]:
    # Named inputs of a form as the browser would send them
    data = {}
    for input in form.find_all("input"):
        if not isinstance(input, Tag) or not (name := input.get("name")):
            continue
        if input.get("type") in ("checkbox", "radio") and not input.has_attr("checked"):
            continue  # Browsers don't send these either
        data[str(name)] = str(input.get("value", ""))
    return data


def _login_error(soup: BeautifulSoup) -> str:
    # Error elements of the Shibboleth IdP default login page, Uni Freiburg and KIT
    error = soup.select_one('.output--error, .errorMessage, .KIT_section[style*="color: red"]')
    if error and (text := error.get_text(" ", strip=True)):
        return text
    return "Login form returned, credentials were likely rejected"


async def _post(session: aiohttp.ClientSession, url: str, data: Any) -> tuple[BeautifulSoup, str]:
    async with session.post(url, data=data) as response:
        return soupify(await response.read()), str(response.url)
