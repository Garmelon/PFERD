import asyncio
from http.cookiejar import LWPCookieJar
from pathlib import Path, PurePath
from typing import Dict, List, Optional

import requests

from ..auth import Authenticator
from ..config import Config
from ..logging import log
from ..utils import fmt_real_path
from ..version import NAME, VERSION
from .crawler import Crawler, CrawlerSection


class HttpCrawlerSection(CrawlerSection):
    def http_timeout(self) -> float:
        return self.s.getfloat("http_timeout", fallback=20)


class HttpCrawler(Crawler):
    COOKIE_FILE = PurePath(".cookies")

    def __init__(
            self,
            name: str,
            section: HttpCrawlerSection,
            config: Config,
            shared_auth: Optional[Authenticator] = None,
    ) -> None:
        super().__init__(name, section, config)

        self._authentication_id = 0
        self._authentication_lock = asyncio.Lock()
        self._http_timeout = section.http_timeout()  # TODO Use or remove

        self._cookie_jar = LWPCookieJar()
        self._cookie_jar_path = self._output_dir.resolve(self.COOKIE_FILE)
        self._shared_cookie_jar_paths: Optional[List[Path]] = None
        self._shared_auth = shared_auth

        self._output_dir.register_reserved(self.COOKIE_FILE)

    async def _current_auth_id(self) -> int:
        """
        Returns the id for the current authentication, i.e. an identifier for the last
        successful call to [authenticate].

        This method must be called before any request that might authenticate is made, so the
        HttpCrawler can properly track when [authenticate] can return early and when actual
        authentication is necessary.
        """
        # We acquire the lock here to ensure we wait for any concurrent authenticate to finish.
        # This should reduce the amount of requests we make: If an authentication is in progress
        # all future requests wait for authentication to complete.
        async with self._authentication_lock:
            return self._authentication_id

    async def authenticate(self, caller_auth_id: int) -> None:
        """
        Starts the authentication process. The main work is offloaded to _authenticate, which
        you should overwrite in a subclass if needed. This method should *NOT* be overwritten.

        The [caller_auth_id] should be the result of a [_current_auth_id] call made *before*
        the request was made. This ensures that authentication is not performed needlessly.
        """
        async with self._authentication_lock:
            log.explain_topic("Authenticating")
            # Another thread successfully called authenticate in-between
            # We do not want to perform auth again, so we return here. We can
            # assume the other thread suceeded as authenticate will throw an error
            # if it failed and aborts the crawl process.
            if caller_auth_id != self._authentication_id:
                log.explain(
                    "Authentication skipped due to auth id mismatch."
                    "A previous authentication beat us to the race."
                )
                return
            log.explain("Calling crawler-specific authenticate")
            await self._authenticate()
            self._authentication_id += 1
            # Saving the cookies after the first auth ensures we won't need to re-authenticate
            # on the next run, should this one be aborted or crash
            self._save_cookies()

    async def _authenticate(self) -> None:
        """
        Performs authentication. This method must only return normally if authentication suceeded.
        In all other cases it must either retry internally or throw a terminal exception.
        """
        raise RuntimeError("_authenticate() was called but crawler doesn't provide an implementation")

    def share_cookies(self, shared: Dict[Authenticator, List[Path]]) -> None:
        if not self._shared_auth:
            return

        if self._shared_auth in shared:
            self._shared_cookie_jar_paths = shared[self._shared_auth]
        else:
            self._shared_cookie_jar_paths = []
            shared[self._shared_auth] = self._shared_cookie_jar_paths

        self._shared_cookie_jar_paths.append(self._cookie_jar_path)

    def _load_cookies(self) -> None:
        log.explain_topic("Loading cookies")

        cookie_jar_path: Optional[Path] = None

        if self._shared_cookie_jar_paths is None:
            log.explain("Not sharing cookies")
            cookie_jar_path = self._cookie_jar_path
        else:
            log.explain("Sharing cookies")
            max_mtime: Optional[float] = None
            for path in self._shared_cookie_jar_paths:
                if not path.is_file():
                    log.explain(f"{fmt_real_path(path)} is not a file")
                    continue
                mtime = path.stat().st_mtime
                if max_mtime is None or mtime > max_mtime:
                    log.explain(f"{fmt_real_path(path)} has newest mtime so far")
                    max_mtime = mtime
                    cookie_jar_path = path
                else:
                    log.explain(f"{fmt_real_path(path)} has older mtime")

        if cookie_jar_path is None:
            log.explain("Couldn't find a suitable cookie file")
            return

        log.explain(f"Loading cookies from {fmt_real_path(cookie_jar_path)}")
        try:
            self._cookie_jar.load(filename=str(cookie_jar_path))
        except Exception as e:
            log.explain(f"Failed to load cookies: {e}")
            log.explain("Proceeding without cookies")

    def _save_cookies(self) -> None:
        log.explain_topic("Saving cookies")

        try:
            log.explain(f"Saving cookies to {fmt_real_path(self._cookie_jar_path)}")
            self._cookie_jar.save(filename=str(self._cookie_jar_path))
        except Exception as e:
            log.warn(f"Failed to save cookies: {e}")

    async def run(self) -> None:
        self._request_count = 0
        self._load_cookies()

        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"{NAME}/{VERSION}"

        # From the request docs: "All requests code should work out of the box
        # with externally provided instances of CookieJar, e.g. LWPCookieJar and
        # FileCookieJar."
        # https://requests.readthedocs.io/en/latest/api/#requests.cookies.RequestsCookieJar
        self.session.cookies = self._cookie_jar  # type: ignore

        with self.session:
            try:
                await super().run()
            finally:
                del self.session

        # They are saved in authenticate, but a final save won't hurt
        self._save_cookies()
