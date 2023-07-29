import re
import asyncio
import aiohttp
from aiohttp import hdrs
from configparser import SectionProxy
from pathlib import PurePath
from typing import Any, Awaitable, Coroutine, Dict, List, Optional, Set, Union, cast

from bs4 import BeautifulSoup, Tag

from ...auth import Authenticator
from ...config import Config
from ...logging import ProgressBar, log
from ...output_dir import FileSink, Redownload
from ...utils import fmt_path, soupify, url_set_query_param
from ..crawler import CrawlError, CrawlToken, CrawlWarning, DownloadToken, anoncritical
from ..http_crawler import HttpCrawler, HttpCrawlerSection
from .async_helpers import _iorepeat
from .file_templates import Links
from .ilias_html_cleaner import clean, insert_base_markup
from .kit_ilias_html import (IliasElementType, IliasForumThread, IliasPage, IliasPageElement,
                             parse_ilias_forum_export, _sanitize_path_name)


TargetType = Union[str, int]


class IliasConfig():
    def __init__(self, base_url: str, client_id: str):
        self._base_url = base_url
        self._client_id = client_id

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def client_id(self) -> str:
        return self._client_id


class IliasWebCrawlerSection(HttpCrawlerSection):
    def __init__(self, section: SectionProxy):
        super().__init__(section)

    def conf(self) -> IliasConfig:
        base_url = self.s.get("base_url")
        if not base_url:
            self.missing_value("base_url")

        client_id = self.s.get("client_id")
        if not client_id:
            self.missing_value("client_id")

        return IliasConfig(base_url, client_id)

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
        if target.startswith(self.conf().base_url):
            # ILIAS URL
            return target

        self.invalid_value("target", target, "Should be <course id | desktop | ilias URL>")

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

    def forums(self) -> bool:
        return self.s.getboolean("forums", fallback=False)


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

class IliasWebCrawler(HttpCrawler):
    def __init__(
            self,
            name: str,
            section: IliasWebCrawlerSection,
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

        self._auth = auth
        self._conf = section.conf()

        self._target = section.target()
        self._link_file_redirect_delay = section.link_redirect_delay()
        self._links = section.links()
        self._videos = section.videos()
        self._forums = section.forums()
        self._visited_urls: Dict[str, PurePath] = dict()

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
            self._conf.base_url + "/goto.php", "target", f"crs_{course_id}"
        )

        await self._crawl_url(root_url, expected_id=course_id)

    async def _crawl_desktop(self) -> None:
        appendix = r"ILIAS\PersonalDesktop\PDMainBarProvider|mm_pd_sel_items"
        appendix = appendix.encode("ASCII").hex()
        await self._crawl_url(self._conf.base_url + "/gs_content.php?item=" + appendix)

    async def _crawl_url(self, url: str, expected_id: Optional[int] = None) -> None:
        maybe_cl = await self.crawl(PurePath("."))
        if not maybe_cl:
            return
        cl = maybe_cl  # Not mypy's fault, but explained here: https://github.com/python/mypy/issues/2608

        elements: List[IliasPageElement] = []
        # A list as variable redefinitions are not propagated to outer scopes
        description: List[BeautifulSoup] = []

        @_iorepeat(3, "crawling url")
        async def gather_elements() -> None:
            elements.clear()
            async with cl:
                next_stage_url: Optional[str] = url
                current_parent = None

                # Duplicated code, but the root page is special - we want to avoid fetching it twice!
                while next_stage_url:
                    soup = await self._get_page(next_stage_url)

                    if current_parent is None and expected_id is not None:
                        perma_link_element: Tag = soup.find(id="current_perma_link")
                        if not perma_link_element or "crs_" not in perma_link_element.get("value"):
                            raise CrawlError("Invalid course id? Didn't find anything looking like a course")

                    log.explain_topic(f"Parsing HTML page for {fmt_path(cl.path)}")
                    log.explain(f"URL: {next_stage_url}")
                    page = IliasPage(soup, next_stage_url, current_parent)
                    if next_element := page.get_next_stage_element():
                        current_parent = next_element
                        next_stage_url = next_element.url
                    else:
                        next_stage_url = None

                elements.extend(page.get_child_elements())
                if description_string := page.get_description():
                    description.append(description_string)

        # Fill up our task list with the found elements
        await gather_elements()

        if description:
            await self._download_description(PurePath("."), description[0])

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
    ) -> Optional[Coroutine[Any, Any, None]]:
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
        # A list as variable redefinitions are not propagated to outer scopes
        description: List[BeautifulSoup] = []

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
                if description_string := page.get_description():
                    description.append(description_string)

        # Fill up our task list with the found elements
        await gather_elements()

        if description:
            await self._download_description(cl.path, description[0])

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
    ) -> Optional[Coroutine[Any, Any, None]]:
        if element.url in self._visited_urls:
            raise CrawlWarning(
                f"Found second path to element {element.name!r} at {element.url!r}. "
                + f"First path: {fmt_path(self._visited_urls[element.url])}. "
                + f"Second path: {fmt_path(parent_path)}."
            )
        self._visited_urls[element.url] = parent_path

        element_path = PurePath(parent_path, element.name)

        if element.type in _VIDEO_ELEMENTS:
            if not self._videos:
                log.status(
                    "[bold bright_black]",
                    "Ignored",
                    fmt_path(element_path),
                    "[bright_black](enable with option 'videos')"
                )
                return None

        if element.type == IliasElementType.FILE:
            return await self._handle_file(element, element_path)
        elif element.type == IliasElementType.FORUM:
            if not self._forums:
                log.status(
                    "[bold bright_black]",
                    "Ignored",
                    fmt_path(element_path),
                    "[bright_black](enable with option 'forums')"
                )
                return None
            return await self._handle_forum(element, element_path)
        elif element.type == IliasElementType.TEST:
            log.status(
                "[bold bright_black]",
                "Ignored",
                fmt_path(element_path),
                "[bright_black](tests contain no relevant data)"
            )
            return None
        elif element.type == IliasElementType.SURVEY:
            log.status(
                "[bold bright_black]",
                "Ignored",
                fmt_path(element_path),
                "[bright_black](surveys contain no relevant data)"
            )
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
    ) -> Optional[Coroutine[Any, Any, None]]:
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
    ) -> Optional[Coroutine[Any, Any, None]]:
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
    @_iorepeat(1, "downloading description")
    async def _download_description(self, parent_path: PurePath, description: BeautifulSoup) -> None:
        path = parent_path / "Description.html"
        dl = await self.download(path, redownload=Redownload.ALWAYS)
        if not dl:
            return

        async with dl as (bar, sink):
            description = clean(insert_base_markup(description))
            sink.file.write(description.prettify().encode("utf-8"))
            sink.done()

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

        await self._authenticate()

        async with self.session.get(export_url, allow_redirects=False) as resp:
            # No redirect means we were authenticated
            if hdrs.LOCATION not in resp.headers:
                return soupify(await resp.read()).select_one("a").get("href").strip()

        raise CrawlError("resolve_link_target failed even after authenticating")

    async def _handle_video(
        self,
        element: IliasPageElement,
        element_path: PurePath,
    ) -> Optional[Coroutine[Any, Any, None]]:
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
        maybe_dl = await self.download(element_path, mtime=element.mtime, redownload=Redownload.ALWAYS)

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
                transformed_path = self._to_local_video_path(video)
                if transformed_path:
                    exists_locally = self._output_dir.resolve(transformed_path).exists()
                    all_found_locally = all_found_locally and exists_locally
            if all_found_locally:
                log.explain("Found all videos locally, skipping enumeration request")
                return True
            log.explain("Missing at least one video, continuing with requests!")
        return False

    def _to_local_video_path(self, path: PurePath) -> Optional[PurePath]:
        if transformed := self._transformer.transform(path):
            return self._deduplicator.fixup_path(transformed)
        return None

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

                transformed_path = self._to_local_video_path(original_path)
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
    ) -> Optional[Coroutine[Any, Any, None]]:
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

    async def _handle_forum(
        self,
        element: IliasPageElement,
        element_path: PurePath,
    ) -> Optional[Coroutine[Any, Any, None]]:
        maybe_cl = await self.crawl(element_path)
        if not maybe_cl:
            return None
        return self._crawl_forum(element, maybe_cl)

    @_iorepeat(3, "crawling forum")
    @anoncritical
    async def _crawl_forum(self, element: IliasPageElement, cl: CrawlToken) -> None:
        elements: List[IliasForumThread] = []

        async with cl:
            next_stage_url = element.url
            while next_stage_url:
                log.explain_topic(f"Parsing HTML page for {fmt_path(cl.path)}")
                log.explain(f"URL: {next_stage_url}")

                soup = await self._get_page(next_stage_url)
                page = IliasPage(soup, next_stage_url, None)

                if next := page.get_next_stage_element():
                    next_stage_url = next.url
                else:
                    break

            download_data = page.get_download_forum_data()
            if not download_data:
                raise CrawlWarning("Failed to extract forum data")
            if download_data.empty:
                log.explain("Forum had no threads")
                elements = []
                return
            html = await self._post_authenticated(download_data.url, download_data.form_data)
            elements = parse_ilias_forum_export(soupify(html))

        elements.sort(key=lambda elem: elem.title)

        tasks: List[Awaitable[None]] = []
        for elem in elements:
            tasks.append(asyncio.create_task(self._download_forum_thread(cl.path, elem)))

        # And execute them
        await self.gather(tasks)

    @anoncritical
    @_iorepeat(3, "saving forum thread")
    async def _download_forum_thread(
        self,
        parent_path: PurePath,
        element: IliasForumThread,
    ) -> None:
        path = parent_path / (_sanitize_path_name(element.title) + ".html")
        maybe_dl = await self.download(path, mtime=element.mtime)
        if not maybe_dl:
            return

        async with maybe_dl as (bar, sink):
            content = element.title_tag.prettify()
            content += element.content_tag.prettify()
            sink.file.write(content.encode("utf-8"))
            sink.done()

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

    async def _post_authenticated(
        self,
        url: str,
        data: dict[str, Union[str, List[str]]]
    ) -> BeautifulSoup:
        auth_id = await self._current_auth_id()

        form_data = aiohttp.FormData()
        for key, val in data.items():
            form_data.add_field(key, val)

        async with self.session.post(url, data=form_data(), allow_redirects=False) as request:
            if request.status == 200:
                return await request.read()

        # We weren't authenticated, so try to do that
        await self.authenticate(auth_id)

        # Retry once after authenticating. If this fails, we will die.
        async with self.session.post(url, data=data, allow_redirects=False) as request:
            if request.status == 200:
                return await request.read()
        raise CrawlError("post_authenticated failed even after authenticating")

    async def _authenticate(self) -> None:
        # fill the session with the correct cookies
        params = {
            "client_id": self._conf.client_id,
            "cmd": "force_login",
        }
        async with self.session.get(f"{ self._conf.base_url }/login.php", params=params) as request:
            login_page = soupify(await request.read())

        login_form = login_page.find("form", attrs={"name": "formlogin"})
        if login_form is None:
            raise CrawlError("Could not find the login form! Specified client id might be invalid.")

        login_url = login_form.attrs.get("action")
        if login_url is None:
            raise CrawlError("Could not find the action URL in the login form!")

        username, password = await self._auth.credentials()

        login_data = {
                "username": username,
                "password": password,
                "cmd[doStandardAuthentication]": "Login",
                }

        # do the actual login
        async with self.session.post(f"{ self._conf.base_url }/{ login_url }", data=login_data) as request:
            soup = soupify(await request.read())
            if not self._is_logged_in(soup):
                self._auth.invalidate_credentials()

    @ staticmethod
    def _is_logged_in(soup: BeautifulSoup) -> bool:
        # Normal ILIAS pages
        mainbar: Optional[Tag] = soup.find(class_="il-maincontrols-metabar")
        if mainbar is not None:
            login_button = mainbar.find(attrs={"href": lambda x: x and "login.php" in x})
            shib_login = soup.find(id="button_shib_login")
            return not login_button and not shib_login

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
