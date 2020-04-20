import logging
from http.cookiejar import LoadError, LWPCookieJar
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

class CookieJar:

    def __init__(self, cookie_file: Optional[Path] = None) -> None:
        self._cookies: LWPCookieJar
        if cookie_file is None:
            self._cookies = LWPCookieJar()
        else:
            self._cookies = LWPCookieJar(cookie_file)

    @property
    def cookies(self) -> LWPCookieJar:
        return self._cookies

    def load_cookies(self) -> None:
        if self._cookies.filename is None:
            return

        try:
            logger.info(f"Loading old cookies from {self._cookies.filename}")
            self._cookies.load(ignore_discard=True)
        except (FileNotFoundError, LoadError):
            logger.warn(
                f"No valid cookie file found at {self._cookies.filename}, "
                "continuing with no cookies"
            )

    def save_cookies(self, reason: Optional[str] = None) -> None:
        if self._cookies.filename is None:
            return

        if reason is None:
            logger.info("Saving cookies")
        else:
            logger.info(f"Saving cookies ({reason})")

        # TODO figure out why ignore_discard is set
        # TODO possibly catch a few more exceptions
        self._cookies.save(ignore_discard=True)

    def create_session(self) -> requests.Session:
        sess = requests.Session()

        # From the request docs: "All requests code should work out of the box
        # with externally provided instances of CookieJar, e.g. LWPCookieJar
        # and FileCookieJar."
        sess.cookies = self.cookies # type: ignore

        return sess
