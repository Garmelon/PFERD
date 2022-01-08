import asyncio
import re
from pathlib import PurePath
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, TypeVar, Union, cast

import aiohttp
from aiohttp import hdrs
from bs4 import BeautifulSoup, Tag

from ...auth import Authenticator, TfaAuthenticator
from ...config import Config
from ...logging import ProgressBar, log
from ...output_dir import FileSink, Redownload
from ...utils import fmt_path, soupify, url_set_query_param
from ..crawler import CrawlError, CrawlToken, CrawlWarning, DownloadToken, anoncritical
from ..http_crawler import HttpCrawler, HttpCrawlerSection
from .file_templates import Links
from .kit_ilias_html import IliasElementType, IliasPage, IliasPageElement

TargetType = Union[str, int]


class KitIliasWebCrawlerSection(HttpCrawlerSection):
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
        value: Optional[str] = self.s.get("tfa_auth")
        if value is None:
            return None
        auth = authenticators.get(value)
        if auth is None:
            self.invalid_value("tfa_auth", value, "No such auth section exists")
        return auth

    def links(self) -> Links:
        type_str: Optional[str] = self.s.get("links")

        if type_str is None:
            return Links.FANCY

        try:
            return Links.from_string(type_str)
        except ValueError as e:
            self.invalid_value("links", type_str, str(e).capitalize())

    def link_redirect_delay(self) -> int:
        return self.s.getint("link_redirect_delay", fallback=-1)

    def videos(self) -> bool:
        return self.s.getboolean("videos", fallback=False)


_DIRECTORY_PAGES: Set[IliasElementType] = set([
    IliasElementType.EXERCISE,
    IliasElementType.EXERCISE_FILES,
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

AWrapped = TypeVar("AWrapped", bound=Callable[..., Awaitable[Optional[Any]]])


def _iorepeat(attempts: int, name: str, failure_is_error: bool = False) -> Callable[[AWrapped], AWrapped]:
    def decorator(f: AWrapped) -> AWrapped:
        async def wrapper(*args: Any, **kwargs: Any) -> Optional[Any]:
            last_exception: Optional[BaseException] = None
            for round in range(attempts):
                try:
                    return await f(*args, **kwargs)
                except aiohttp.ContentTypeError:  # invalid content type
                    raise CrawlWarning("ILIAS returned an invalid content type")
                except aiohttp.TooManyRedirects:
                    raise CrawlWarning("Got stuck in a redirect loop")
                except aiohttp.ClientPayloadError as e:  # encoding or not enough bytes
                    last_exception = e
                except aiohttp.ClientConnectionError as e:  # e.g. timeout, disconnect, resolve failed, etc.
                    last_exception = e
                except asyncio.exceptions.TimeoutError as e:  # explicit http timeouts in HttpCrawler
                    last_exception = e
                log.explain_topic(f"Retrying operation {name}. Retries left: {attempts - 1 - round}")

            if last_exception:
                message = f"Error in I/O Operation: {last_exception}"
                if failure_is_error:
                    raise CrawlError(message) from last_exception
                else:
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
        # Setting a main authenticator for cookie sharing
        auth = section.auth(authenticators)
        super().__init__(name, section, config, shared_auth=auth)

        if section.tasks() > 1:
            log.warn("""
Please avoid using too many parallel requests as these are the KIT ILIAS
instance's greatest bottleneck.
            """.strip())

        self._shibboleth_login = KitShibbolethLogin(
            auth,
            section.tfa_auth(authenticators),
        )

        self._base_url = "https://ilias.studium.kit.edu"

        self._target = section.target()
        self._link_file_redirect_delay = section.link_redirect_delay()
        self._links = section.links()
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
        appendix = r"ILIAS\PersonalDesktop\PDMainBarProvider|mm_pd_sel_items"
        appendix = appendix.encode("ASCII").hex()
        await self._crawl_url(self._base_url + "/gs_content.php?item=" + appendix)

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

        elements.sort(key=lambda e: e.id())

        tasks: List[Awaitable[None]] = []
        for element in elements:
            if handle := await self._handle_ilias_element(PurePath("."), element):
                tasks.append(asyncio.create_task(handle))

        # And execute them
        await self.gather(tasks)

    async def _handle_ilias_page(
        self,
        url: str,
        parent: IliasPageElement,
        path: PurePath,
    ) -> Optional[Awaitable[None]]:
        maybe_cl = await self.crawl(path)
        if not maybe_cl:
            return None
        return self._crawl_ilias_page(url, parent, maybe_cl)

    @anoncritical
    async def _crawl_ilias_page(
        self,
        url: str,
        parent: IliasPageElement,
        cl: CrawlToken,
    ) -> None:
        elements: List[IliasPageElement] = []

        @_iorepeat(3, "crawling folder")
        async def gather_elements() -> None:
            elements.clear()
            async with cl:
                next_stage_url: Optional[str] = url
                current_parent = parent

                while next_stage_url:
                    soup = await self._get_page(next_stage_url)
                    log.explain_topic(f"Parsing HTML page for {fmt_path(cl.path)}")
                    log.explain(f"URL: {next_stage_url}")
                    page = IliasPage(soup, next_stage_url, current_parent)
                    if next_element := page.get_next_stage_element():
                        current_parent = next_element
                        next_stage_url = next_element.url
                    else:
                        next_stage_url = None

                elements.extend(page.get_child_elements())

        # Fill up our task list with the found elements
        await gather_elements()

        elements.sort(key=lambda e: e.id())

        tasks: List[Awaitable[None]] = []
        for element in elements:
            if handle := await self._handle_ilias_element(cl.path, element):
                tasks.append(asyncio.create_task(handle))

        # And execute them
        await self.gather(tasks)

    # These decorators only apply *to this method* and *NOT* to the returned
    # awaitables!
    # This method does not await the handlers but returns them instead.
    # This ensures one level is handled at a time and name deduplication
    # works correctly.
    @anoncritical
    async def _handle_ilias_element(
        self,
        parent_path: PurePath,
        element: IliasPageElement,
    ) -> Optional[Awaitable[None]]:
        element_path = PurePath(parent_path, element.name)

        if element.type in _VIDEO_ELEMENTS:
            log.explain_topic(f"Decision: Crawl video element {fmt_path(element_path)}")
            if not self._videos:
                log.explain("Video crawling is disabled")
                log.explain("Answer: no")
                return None
            else:
                log.explain("Video crawling is enabled")
                log.explain("Answer: yes")

        if element.type == IliasElementType.FILE:
            return await self._handle_file(element, element_path)
        elif element.type == IliasElementType.FORUM:
            log.explain_topic(f"Decision: Crawl {fmt_path(element_path)}")
            log.explain("Forums are not supported")
            log.explain("Answer: No")
            return None
        elif element.type == IliasElementType.TEST:
            log.explain_topic(f"Decision: Crawl {fmt_path(element_path)}")
            log.explain("Tests contain no relevant files")
            log.explain("Answer: No")
            return None
        elif element.type == IliasElementType.LINK:
            return await self._handle_link(element, element_path)
        elif element.type == IliasElementType.BOOKING:
            return await self._handle_booking(element, element_path)
        elif element.type == IliasElementType.VIDEO:
            return await self._handle_file(element, element_path)
        elif element.type == IliasElementType.VIDEO_PLAYER:
            return await self._handle_video(element, element_path)
        elif element.type in _DIRECTORY_PAGES:
            return await self._handle_ilias_page(element.url, element, element_path)
        else:
            # This will retry it a few times, failing everytime. It doesn't make any network
            # requests, so that's fine.
            raise CrawlWarning(f"Unknown element type: {element.type!r}")

    async def _handle_link(
        self,
        element: IliasPageElement,
        element_path: PurePath,
    ) -> Optional[Awaitable[None]]:
        log.explain_topic(f"Decision: Crawl Link {fmt_path(element_path)}")
        log.explain(f"Links type is {self._links}")

        link_template_maybe = self._links.template()
        link_extension = self._links.extension()
        if not link_template_maybe or not link_extension:
            log.explain("Answer: No")
            return None
        else:
            log.explain("Answer: Yes")
        element_path = element_path.with_name(element_path.name + link_extension)

        maybe_dl = await self.download(element_path, mtime=element.mtime)
        if not maybe_dl:
            return None

        return self._download_link(element, link_template_maybe, maybe_dl)

    @anoncritical
    @_iorepeat(3, "resolving link")
    async def _download_link(self, element: IliasPageElement, link_template: str, dl: DownloadToken) -> None:
        async with dl as (bar, sink):
            export_url = element.url.replace("cmd=calldirectlink", "cmd=exportHTML")
            real_url = await self._resolve_link_target(export_url)
            self._write_link_content(link_template, real_url, element.name, element.description, sink)

    def _write_link_content(
        self,
        link_template: str,
        url: str,
        name: str,
        description: Optional[str],
        sink: FileSink,
    ) -> None:
        content = link_template
        content = content.replace("{{link}}", url)
        content = content.replace("{{name}}", name)
        content = content.replace("{{description}}", str(description))
        content = content.replace("{{redirect_delay}}", str(self._link_file_redirect_delay))
        sink.file.write(content.encode("utf-8"))
        sink.done()

    async def _handle_booking(
        self,
        element: IliasPageElement,
        element_path: PurePath,
    ) -> Optional[Awaitable[None]]:
        log.explain_topic(f"Decision: Crawl Booking Link {fmt_path(element_path)}")
        log.explain(f"Links type is {self._links}")

        link_template_maybe = self._links.template()
        link_extension = self._links.extension()
        if not link_template_maybe or not link_extension:
            log.explain("Answer: No")
            return None
        else:
            log.explain("Answer: Yes")
        element_path = element_path.with_name(element_path.name + link_extension)

        maybe_dl = await self.download(element_path, mtime=element.mtime)
        if not maybe_dl:
            return None

        return self._download_booking(element, link_template_maybe, maybe_dl)

    @anoncritical
    @_iorepeat(3, "resolving booking")
    async def _download_booking(
        self,
        element: IliasPageElement,
        link_template: str,
        dl: DownloadToken,
    ) -> None:
        async with dl as (bar, sink):
            self._write_link_content(link_template, element.url, element.name, element.description, sink)

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

    async def _handle_video(
        self,
        element: IliasPageElement,
        element_path: PurePath,
    ) -> Optional[Awaitable[None]]:
        # Copy old mapping as it is likely still relevant
        if self.prev_report:
            self.report.add_custom_value(
                str(element_path),
                self.prev_report.get_custom_value(str(element_path))
            )

        # A video might contain other videos, so let's "crawl" the video first
        # to ensure rate limits apply. This must be a download as *this token*
        # is re-used if the video consists of a single stream. In that case the
        # file name is used and *not* the stream name the ilias html parser reported
        # to ensure backwards compatibility.
        maybe_dl = await self.download(element_path, redownload=Redownload.ALWAYS)

        # If we do not want to crawl it (user filter) or we have every file
        # from the cached mapping already, we can ignore this and bail
        if not maybe_dl or self._all_videos_locally_present(element_path):
            # Mark all existing cideos as known so they do not get deleted
            # during dleanup. We "downloaded" them, just without actually making
            # a network request as we assumed they did not change.
            for video in self._previous_contained_videos(element_path):
                await self.download(video)

            return None

        return self._download_video(element_path, element, maybe_dl)

    def _previous_contained_videos(self, video_path: PurePath) -> List[PurePath]:
        if not self.prev_report:
            return []
        custom_value = self.prev_report.get_custom_value(str(video_path))
        if not custom_value:
            return []
        names = cast(List[str], custom_value)
        folder = video_path.parent
        return [PurePath(folder, name) for name in names]

    def _all_videos_locally_present(self, video_path: PurePath) -> bool:
        if contained_videos := self._previous_contained_videos(video_path):
            log.explain_topic(f"Checking local cache for video {video_path.name}")
            all_found_locally = True
            for video in contained_videos:
                transformed_path = self._transformer.transform(video)
                if transformed_path:
                    exists_locally = self._output_dir.resolve(transformed_path).exists()
                    all_found_locally = all_found_locally and exists_locally
            if all_found_locally:
                log.explain("Found all videos locally, skipping enumeration request")
                return True
            log.explain("Missing at least one video, continuing with requests!")
        return False

    @anoncritical
    @_iorepeat(3, "downloading video")
    async def _download_video(
        self,
        original_path: PurePath,
        element: IliasPageElement,
        dl: DownloadToken
    ) -> None:
        stream_elements: List[IliasPageElement] = []
        async with dl as (bar, sink):
            page = IliasPage(await self._get_page(element.url), element.url, element)
            stream_elements = page.get_child_elements()

            if len(stream_elements) > 1:
                log.explain(f"Found multiple video streams for {element.name}")
            else:
                log.explain(f"Using single video mode for {element.name}")
                stream_element = stream_elements[0]

                transformed_path = self._transformer.transform(original_path)
                if not transformed_path:
                    raise CrawlError(f"Download returned a path but transform did not for {original_path}")

                # We do not have a local cache yet
                if self._output_dir.resolve(transformed_path).exists():
                    log.explain(f"Video for {element.name} existed locally")
                else:
                    await self._stream_from_url(stream_element.url, sink, bar, is_video=True)
                self.report.add_custom_value(str(original_path), [original_path.name])
                return

        contained_video_paths: List[str] = []

        for stream_element in stream_elements:
            video_path = original_path.parent / stream_element.name
            contained_video_paths.append(str(video_path))

            maybe_dl = await self.download(video_path, mtime=element.mtime, redownload=Redownload.NEVER)
            if not maybe_dl:
                continue
            async with maybe_dl as (bar, sink):
                log.explain(f"Streaming video from real url {stream_element.url}")
                await self._stream_from_url(stream_element.url, sink, bar, is_video=True)

        self.report.add_custom_value(str(original_path), contained_video_paths)

    async def _handle_file(
        self,
        element: IliasPageElement,
        element_path: PurePath,
    ) -> Optional[Awaitable[None]]:
        maybe_dl = await self.download(element_path, mtime=element.mtime)
        if not maybe_dl:
            return None
        return self._download_file(element, maybe_dl)

    @anoncritical
    @_iorepeat(3, "downloading file")
    async def _download_file(self, element: IliasPageElement, dl: DownloadToken) -> None:
        assert dl  # The function is only reached when dl is not None
        async with dl as (bar, sink):
            await self._stream_from_url(element.url, sink, bar, is_video=False)

    async def _stream_from_url(self, url: str, sink: FileSink, bar: ProgressBar, is_video: bool) -> None:
        async def try_stream() -> bool:
            async with self.session.get(url, allow_redirects=is_video) as resp:
                if not is_video:
                    # Redirect means we weren't authenticated
                    if hdrs.LOCATION in resp.headers:
                        return False
                # we wanted a video but got HTML
                if is_video and "html" in resp.content_type:
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
    @_iorepeat(3, "Login", failure_is_error=True)
    async def _authenticate(self) -> None:
        await self._shibboleth_login.login(self.session)

    @staticmethod
    def _is_logged_in(soup: BeautifulSoup) -> bool:
        # Normal ILIAS pages
        mainbar: Optional[Tag] = soup.find(class_="il-maincontrols-metabar")
        if mainbar is not None:
            login_button = mainbar.find("button", attrs={"data-action": lambda x: x and "login.php" in x})
            return not login_button

        # Personal Desktop
        if soup.find("a", attrs={"href": lambda x: x and "block_type=pditems" in x}):
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
            self._tfa_auth = TfaAuthenticator("ilias-anon-tfa")

        tfa_token = await self._tfa_auth.password()

        # Searching the form here so that this fails before asking for
        # credentials rather than after asking.
        form = soup.find("form", {"method": "post"})
        action = form["action"]
        csrf_token = form.find("input", {"name": "csrf_token"})["value"]

        # Equivalent: Enter token in
        # https://idp.scc.kit.edu/idp/profile/SAML2/Redirect/SSO
        url = "https://idp.scc.kit.edu" + action
        data = {
            "_eventId_proceed": "",
            "j_tokenNumber": tfa_token,
            "csrf_token": csrf_token
        }
        return await _post(session, url, data)

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
