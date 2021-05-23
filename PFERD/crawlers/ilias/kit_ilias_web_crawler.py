import re
from pathlib import PurePath
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, TypeVar, Union

import aiohttp
from aiohttp import hdrs
from bs4 import BeautifulSoup, Tag

from PFERD.authenticators import Authenticator
from PFERD.config import Config
from PFERD.crawler import CrawlError, CrawlerSection, CrawlWarning, anoncritical
from PFERD.http_crawler import HttpCrawler
from PFERD.logging import ProgressBar, log
from PFERD.output_dir import FileSink, Redownload
from PFERD.utils import soupify, url_set_query_param

from ...utils import fmt_path
from .file_templates import link_template_plain, link_template_rich
from .kit_ilias_html import IliasElementType, IliasPage, IliasPageElement

TargetType = Union[str, int]


class KitIliasWebCrawlerSection(CrawlerSection):

    def target(self) -> TargetType:
        target = self.s.get("target")
        if not target:
            self.missing_value("target")

        if re.fullmatch(r"\d+", target):
            # Course id
            return int(target)
        if target == "desktop":
            # Full personal desktop
            return target
        if target.startswith("https://ilias.studium.kit.edu"):
            # ILIAS URL
            return target

        self.invalid_value("target", target, "Should be <course id | desktop | kit ilias URL>")

    def tfa_auth(self, authenticators: Dict[str, Authenticator]) -> Optional[Authenticator]:
        value = self.s.get("tfa_auth")
        if not value:
            return None

        auth = authenticators.get(f"auth:{value}")
        if auth is None:
            self.invalid_value("auth", value, "No such auth section exists")
        return auth

    def link_file_redirect_delay(self) -> int:
        return self.s.getint("link_file_redirect_delay", fallback=-1)

    def link_file_use_plaintext(self) -> bool:
        return self.s.getboolean("link_file_plaintext", fallback=False)

    def videos(self) -> bool:
        return self.s.getboolean("videos", fallback=False)


_DIRECTORY_PAGES: Set[IliasElementType] = set([
    IliasElementType.EXERCISE,
    IliasElementType.FOLDER,
    IliasElementType.MEETING,
    IliasElementType.VIDEO_FOLDER,
    IliasElementType.VIDEO_FOLDER_MAYBE_PAGINATED,
])

_VIDEO_ELEMENTS: Set[IliasElementType] = set([
    IliasElementType.VIDEO,
    IliasElementType.VIDEO_PLAYER,
    IliasElementType.VIDEO_FOLDER,
    IliasElementType.VIDEO_FOLDER_MAYBE_PAGINATED,
])

AWrapped = TypeVar("AWrapped", bound=Callable[..., Awaitable[None]])


def _iorepeat(attempts: int, name: str) -> Callable[[AWrapped], AWrapped]:
    def decorator(f: AWrapped) -> AWrapped:
        async def wrapper(*args: Any, **kwargs: Any) -> None:
            last_exception: Optional[BaseException] = None
            for round in range(attempts):
                try:
                    await f(*args, **kwargs)
                    return
                except aiohttp.ContentTypeError:  # invalid content type
                    raise CrawlWarning("ILIAS returned an invalid content type")
                except aiohttp.TooManyRedirects:
                    raise CrawlWarning("Got stuck in a redirect loop")
                except aiohttp.ClientPayloadError as e:  # encoding or not enough bytes
                    last_exception = e
                except aiohttp.ClientConnectionError as e:  # e.g. timeout, disconnect, resolve failed, etc.
                    last_exception = e
                log.explain_topic(f"Retrying operation {name}. Retries left: {attempts - 1 - round}")

            if last_exception:
                message = f"Error in I/O Operation: {last_exception}"
                raise CrawlWarning(message) from last_exception
            raise CrawlError("Impossible return in ilias _iorepeat")

        return wrapper  # type: ignore
    return decorator


def _wrap_io_in_warning(name: str) -> Callable[[AWrapped], AWrapped]:
    """
    Wraps any I/O exception in a CrawlWarning.
    """
    return _iorepeat(1, name)


# Crawler control flow:
#
#     crawl_desktop -+
#                    |
#     crawl_course --+
#                    |
#     @_io_repeat    |        # retries internally (before the bar)
#  +- crawl_url    <-+
#  |
#  |
#  |  @_wrap_io_exception     # does not need to retry as children acquire bars
#  +> crawl_ilias_element -+
#  ^                       |
#  |  @_io_repeat          |  # retries internally (before the bar)
#  +- crawl_ilias_page <---+
#  |                       |
#  +> get_page             |  # Handles and retries authentication
#                          |
#     @_io_repeat          |  # retries internally (before the bar)
#  +- download_link    <---+
#  |                       |
#  +> resolve_target       |  # Handles and retries authentication
#                          |
#     @_io_repeat          |  # retries internally (before the bar)
#  +- download_video   <---+
#  |                       |
#  |  @_io_repeat          |  # retries internally (before the bar)
#  +- download_file    <---+
#  |
#  +> stream_from_url         # Handles and retries authentication

class KitIliasWebCrawler(HttpCrawler):
    def __init__(
            self,
            name: str,
            section: KitIliasWebCrawlerSection,
            config: Config,
            authenticators: Dict[str, Authenticator]
    ):
        super().__init__(name, section, config)

        self._shibboleth_login = KitShibbolethLogin(
            section.auth(authenticators),
            section.tfa_auth(authenticators)
        )
        self._base_url = "https://ilias.studium.kit.edu"

        self._target = section.target()
        self._link_file_redirect_delay = section.link_file_redirect_delay()
        self._link_file_use_plaintext = section.link_file_use_plaintext()
        self._videos = section.videos()

    async def _run(self) -> None:
        if isinstance(self._target, int):
            log.explain_topic(f"Inferred crawl target: Course with id {self._target}")
            await self._crawl_course(self._target)
        elif self._target == "desktop":
            log.explain_topic("Inferred crawl target: Personal desktop")
            await self._crawl_desktop()
        else:
            log.explain_topic(f"Inferred crawl target: URL {self._target}")
            await self._crawl_url(self._target)

    async def _crawl_course(self, course_id: int) -> None:
        # Start crawling at the given course
        root_url = url_set_query_param(
            self._base_url + "/goto.php", "target", f"crs_{course_id}"
        )

        await self._crawl_url(root_url, expected_id=course_id)

    async def _crawl_desktop(self) -> None:
        await self._crawl_url(self._base_url)

    async def _crawl_url(self, url: str, expected_id: Optional[int] = None) -> None:
        maybe_cl = await self.crawl(PurePath("."))
        if not maybe_cl:
            return
        cl = maybe_cl  # Not mypy's fault, but explained here: https://github.com/python/mypy/issues/2608

        elements: List[IliasPageElement] = []

        @_iorepeat(3, "crawling url")
        async def gather_elements() -> None:
            elements.clear()
            async with cl:
                soup = await self._get_page(url)

                if expected_id is not None:
                    perma_link_element: Tag = soup.find(id="current_perma_link")
                    if not perma_link_element or "crs_" not in perma_link_element.get("value"):
                        raise CrawlError("Invalid course id? Didn't find anything looking like a course")

                # Duplicated code, but the root page is special - we want to avoid fetching it twice!
                log.explain_topic("Parsing root HTML page")
                log.explain(f"URL: {url}")
                page = IliasPage(soup, url, None)
                elements.extend(page.get_child_elements())

        # Fill up our task list with the found elements
        await gather_elements()
        tasks = [self._handle_ilias_element(PurePath("."), element) for element in elements]

        # And execute them
        await self.gather(tasks)

    async def _handle_ilias_page(self, url: str, parent: IliasPageElement, path: PurePath) -> None:
        maybe_cl = await self.crawl(path)
        if not maybe_cl:
            return
        cl = maybe_cl  # Not mypy's fault, but explained here: https://github.com/python/mypy/issues/2608

        elements: List[IliasPageElement] = []

        @_iorepeat(3, "crawling folder")
        async def gather_elements() -> None:
            elements.clear()
            async with cl:
                soup = await self._get_page(url)
                log.explain_topic(f"Parsing HTML page for {fmt_path(path)}")
                log.explain(f"URL: {url}")
                page = IliasPage(soup, url, parent)

                elements.extend(page.get_child_elements())

        # Fill up our task list with the found elements
        await gather_elements()
        tasks = [self._handle_ilias_element(path, element) for element in elements]

        # And execute them
        await self.gather(tasks)

    @anoncritical
    # Shouldn't happen but we also really don't want to let I/O errors bubble up to anoncritical.
    # If that happens we will be terminated as anoncritical doesn't tream them as non-critical.
    @_wrap_io_in_warning("handling ilias element")
    async def _handle_ilias_element(self, parent_path: PurePath, element: IliasPageElement) -> None:
        element_path = PurePath(parent_path, element.name)

        if element.type in _VIDEO_ELEMENTS:
            log.explain_topic(f"Decision: Crawl video element {fmt_path(element_path)}")
            if not self._videos:
                log.explain("Video crawling is disabled")
                log.explain("Answer: no")
                return
            else:
                log.explain("Video crawling is enabled")
                log.explain("Answer: yes")

        if element.type == IliasElementType.FILE:
            await self._download_file(element, element_path)
        elif element.type == IliasElementType.FORUM:
            log.explain_topic(f"Decision: Crawl {fmt_path(element_path)}")
            log.explain("Forums are not supported")
            log.explain("Answer: No")
        elif element.type == IliasElementType.LINK:
            await self._download_link(element, element_path)
        elif element.type == IliasElementType.VIDEO:
            await self._download_file(element, element_path)
        elif element.type == IliasElementType.VIDEO_PLAYER:
            await self._download_video(element, element_path)
        elif element.type in _DIRECTORY_PAGES:
            await self._handle_ilias_page(element.url, element, element_path)
        else:
            # This will retry it a few times, failing everytime. It doesn't make any network
            # requests, so that's fine.
            raise CrawlWarning(f"Unknown element type: {element.type!r}")

    async def _download_link(self, element: IliasPageElement, element_path: PurePath) -> None:
        maybe_dl = await self.download(element_path, mtime=element.mtime)
        if not maybe_dl:
            return
        dl = maybe_dl  # Not mypy's fault, but explained here: https://github.com/python/mypy/issues/2608

        @_iorepeat(3, "resolving link")
        async def impl() -> None:
            async with dl as (bar, sink):
                export_url = element.url.replace("cmd=calldirectlink", "cmd=exportHTML")
                real_url = await self._resolve_link_target(export_url)

                content = link_template_plain if self._link_file_use_plaintext else link_template_rich
                content = content.replace("{{link}}", real_url)
                content = content.replace("{{name}}", element.name)
                content = content.replace("{{description}}", str(element.description))
                content = content.replace("{{redirect_delay}}", str(self._link_file_redirect_delay))
                sink.file.write(content.encode("utf-8"))
                sink.done()

        await impl()

    async def _resolve_link_target(self, export_url: str) -> str:
        async with self.session.get(export_url, allow_redirects=False) as resp:
            # No redirect means we were authenticated
            if hdrs.LOCATION not in resp.headers:
                return soupify(await resp.read()).select_one("a").get("href").strip()

        self._authenticate()

        async with self.session.get(export_url, allow_redirects=False) as resp:
            # No redirect means we were authenticated
            if hdrs.LOCATION not in resp.headers:
                return soupify(await resp.read()).select_one("a").get("href").strip()

        raise CrawlError("resolve_link_target failed even after authenticating")

    async def _download_video(self, element: IliasPageElement, element_path: PurePath) -> None:
        # Videos will NOT be redownloaded - their content doesn't really change and they are chunky
        maybe_dl = await self.download(element_path, mtime=element.mtime, redownload=Redownload.NEVER)
        if not maybe_dl:
            return
        dl = maybe_dl  # Not mypy's fault, but explained here: https://github.com/python/mypy/issues/2608

        @_iorepeat(3, "downloading video")
        async def impl() -> None:
            assert dl  # The function is only reached when dl is not None
            async with dl as (bar, sink):
                page = IliasPage(await self._get_page(element.url), element.url, element)
                real_element = page.get_child_elements()[0]

                await self._stream_from_url(real_element.url, sink, bar)

        await impl()

    async def _download_file(self, element: IliasPageElement, element_path: PurePath) -> None:
        maybe_dl = await self.download(element_path, mtime=element.mtime)
        if not maybe_dl:
            return
        dl = maybe_dl  # Not mypy's fault, but explained here: https://github.com/python/mypy/issues/2608

        @_iorepeat(3, "downloading file")
        async def impl() -> None:
            assert dl  # The function is only reached when dl is not None
            async with dl as (bar, sink):
                await self._stream_from_url(element.url, sink, bar)

        await impl()

    async def _stream_from_url(self, url: str, sink: FileSink, bar: ProgressBar) -> None:
        async def try_stream() -> bool:
            async with self.session.get(url, allow_redirects=False) as resp:
                # Redirect means we weren't authenticated
                if hdrs.LOCATION in resp.headers:
                    return False

                if resp.content_length:
                    bar.set_total(resp.content_length)

                async for data in resp.content.iter_chunked(1024):
                    sink.file.write(data)
                    bar.advance(len(data))

                sink.done()
            return True

        auth_id = await self._current_auth_id()
        if await try_stream():
            return

        await self.authenticate(auth_id)

        if not await try_stream():
            raise CrawlError("File streaming failed after authenticate()")

    async def _get_page(self, url: str) -> BeautifulSoup:
        auth_id = await self._current_auth_id()
        async with self.session.get(url) as request:
            soup = soupify(await request.read())
            if self._is_logged_in(soup):
                return soup

        # We weren't authenticated, so try to do that
        await self.authenticate(auth_id)

        # Retry once after authenticating. If this fails, we will die.
        async with self.session.get(url) as request:
            soup = soupify(await request.read())
            if self._is_logged_in(soup):
                return soup
        raise CrawlError("get_page failed even after authenticating")

    # We repeat this as the login method in shibboleth doesn't handle I/O errors.
    # Shibboleth is quite reliable as well, the repeat is likely not critical here.
    @_iorepeat(3, "Login")
    async def _authenticate(self) -> None:
        await self._shibboleth_login.login(self.session)

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
                self._auth.invalidate_credentials()

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

        tfa_token = await self._tfa_auth.password()

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
