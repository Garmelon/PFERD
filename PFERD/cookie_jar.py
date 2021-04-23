"""A helper for httpx cookies."""

import logging
from http.cookiejar import LoadError, LWPCookieJar
from pathlib import Path
from typing import Optional

import httpx

LOGGER = logging.getLogger(__name__)


class CookieJar:
    """A cookie jar that can be persisted."""

    def __init__(self, cookie_file: Optional[Path] = None) -> None:
        """Create a new cookie jar at the given path.

        If the path is None, the cookies will not be persisted.
        """
        self._cookies: LWPCookieJar
        if cookie_file is None:
            self._cookies = LWPCookieJar()
        else:
            self._cookies = LWPCookieJar(str(cookie_file.resolve()))

    @property
    def cookies(self) -> LWPCookieJar:
        """Return the httpx cookie jar."""
        return self._cookies

    def load_cookies(self) -> None:
        """Load all cookies from the file given in the constructor."""
        if self._cookies.filename is None:
            return

        try:
            LOGGER.info("Loading old cookies from %s", self._cookies.filename)
            self._cookies.load(ignore_discard=True)
        except (FileNotFoundError, LoadError):
            LOGGER.warning(
                "No valid cookie file found at %s, continuing with no cookies",
                self._cookies.filename
            )

    def save_cookies(self, reason: Optional[str] = None) -> None:
        """Save the cookies in the file given in the constructor."""
        if self._cookies.filename is None:
            return

        if reason is None:
            LOGGER.info("Saving cookies")
        else:
            LOGGER.info("Saving cookies (%s)", reason)

        # TODO figure out why ignore_discard is set
        # TODO possibly catch a few more exceptions
        self._cookies.save(ignore_discard=True)

    def create_client(self) -> httpx.Client:
        """Create a new client using the cookie jar."""
        # TODO: timeout=None was the default behaviour of requests. An approprite value should probably be set
        client = httpx.Client(timeout=None)

        client.cookies = self.cookies  # type: ignore

        return client

    def create_async_client(self) -> httpx.AsyncClient:
        """Create a new async client using the cookie jar."""
        # TODO: timeout=None was the default behaviour of requests. An approprite value should probably be set
        client = httpx.AsyncClient(timeout=None)
        client.cookies = self.cookies
        return client
