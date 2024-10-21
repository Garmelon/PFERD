import asyncio
import base64
import os
import re
from collections.abc import Awaitable, Coroutine
from pathlib import PurePath
from typing import Any, Dict, List, Literal, Optional, Set, Union, cast
from urllib.parse import urljoin

import aiohttp
from aiohttp import hdrs
from bs4 import BeautifulSoup, Tag

from ...auth import Authenticator
from ...config import Config
from ...logging import ProgressBar, log
from ...output_dir import FileSink, Redownload
from ...utils import fmt_path, soupify, url_set_query_param
from ..crawler import CrawlError, CrawlToken, CrawlWarning, DownloadToken, anoncritical
from ..http_crawler import HttpCrawler, HttpCrawlerSection
from .async_helper import _iorepeat
from .file_templates import Links, learning_module_template
from .ilias_html_cleaner import clean, insert_base_markup
from .kit_ilias_html import (IliasElementType, IliasForumThread, IliasLearningModulePage, IliasPage,
                             IliasPageElement, _sanitize_path_name, parse_ilias_forum_export)

TargetType = Union[str, int]


class IliasWebCrawlerSection(HttpCrawlerSection):
    def base_url(self) -> str:
        base_url = self.s.get("base_url")
        if not base_url:
            self.missing_value("base_url")

        return base_url

    def client_id(self) -> str:
        client_id = self.s.get("client_id")
        if not client_id:
            self.missing_value("client_id")

        return client_id

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
        if target.startswith(self.base_url()):
            # URL
            return target

        self.invalid_value("target", target, "Should be <course id | desktop | kit ilias URL>")

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


_DIRECTORY_PAGES: Set[IliasElementType] = {
    IliasElementType.EXERCISE,
    IliasElementType.EXERCISE_FILES,
    IliasElementType.FOLDER,
    IliasElementType.INFO_TAB,
    IliasElementType.MEETING,
    IliasElementType.MEDIACAST_VIDEO_FOLDER,
    IliasElementType.OPENCAST_VIDEO_FOLDER,
    IliasElementType.OPENCAST_VIDEO_FOLDER_MAYBE_PAGINATED,
}

_VIDEO_ELEMENTS: Set[IliasElementType] = {
    IliasElementType.MEDIACAST_VIDEO_FOLDER,
    IliasElementType.MEDIACAST_VIDEO,
    IliasElementType.OPENCAST_VIDEO,
    IliasElementType.OPENCAST_VIDEO_PLAYER,
    IliasElementType.OPENCAST_VIDEO_FOLDER,
    IliasElementType.OPENCAST_VIDEO_FOLDER_MAYBE_PAGINATED,
}


def _get_video_cache_key(element: IliasPageElement) -> str:
    return f"ilias-video-cache-{element.id()}"


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
        self._base_url = section.base_url()
        self._client_id = section.client_id()

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
            urljoin(self._base_url, "/goto.php"),
            "target", f"crs_{course_id}",
        )

        await self._crawl_url(root_url, expected_id=course_id)

    async def _crawl_desktop(self) -> None:
        appendix = r"ILIAS\Repository\Provider\RepositoryMainBarProvider|mm_pd_sel_items"
        appendix = appendix.encode("ASCII").hex()
        await self._crawl_url(url_set_query_param(
            urljoin(self._base_url, "/gs_content.php"),
            "item=", appendix,
        ))

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
                    soup = await self._get_page(next_stage_url, root_page_allowed=True)

                    if current_parent is None and expected_id is not None:
                        perma_link = IliasPage.get_soup_permalink(soup)
                        if not perma_link or "crs_" not in perma_link:
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
                if info_tab := page.get_info_tab():
                    elements.append(info_tab)
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

        # element.name might contain `/` if the crawler created nested elements,
        # so we can not sanitize it here. We trust in the output dir to thwart worst-case
        # directory escape attacks.
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
        elif element.type == IliasElementType.SCORM_LEARNING_MODULE:
            log.status(
                "[bold bright_black]",
                "Ignored",
                fmt_path(element_path),
                "[bright_black](scorm learning modules are not supported)"
            )
            return None
        elif element.type == IliasElementType.LEARNING_MODULE:
            return await self._handle_learning_module(element, element_path)
        elif element.type == IliasElementType.LINK:
            return await self._handle_link(element, element_path)
        elif element.type == IliasElementType.BOOKING:
            return await self._handle_booking(element, element_path)
        elif element.type == IliasElementType.OPENCAST_VIDEO:
            return await self._handle_file(element, element_path)
        elif element.type == IliasElementType.OPENCAST_VIDEO_PLAYER:
            return await self._handle_opencast_video(element, element_path)
        elif element.type == IliasElementType.MEDIACAST_VIDEO:
            return await self._handle_file(element, element_path)
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

    async def _handle_opencast_video(
        self,
        element: IliasPageElement,
        element_path: PurePath,
    ) -> Optional[Coroutine[Any, Any, None]]:
        # Copy old mapping as it is likely still relevant
        if self.prev_report:
            self.report.add_custom_value(
                _get_video_cache_key(element),
                self.prev_report.get_custom_value(_get_video_cache_key(element))
            )

        # A video might contain other videos, so let's "crawl" the video first
        # to ensure rate limits apply. This must be a download as *this token*
        # is re-used if the video consists of a single stream. In that case the
        # file name is used and *not* the stream name the ilias html parser reported
        # to ensure backwards compatibility.
        maybe_dl = await self.download(element_path, mtime=element.mtime, redownload=Redownload.ALWAYS)

        # If we do not want to crawl it (user filter), we can move on
        if not maybe_dl:
            return None

        # If we have every file from the cached mapping already, we can ignore this and bail
        if self._all_opencast_videos_locally_present(element, maybe_dl.path):
            # Mark all existing videos as known to ensure they do not get deleted during cleanup.
            # We "downloaded" them, just without actually making a network request as we assumed
            # they did not change.
            contained = self._previous_contained_opencast_videos(element, maybe_dl.path)
            if len(contained) > 1:
                # Only do this if we threw away the original dl token,
                # to not download single-stream videos twice
                for video in contained:
                    await self.download(video)

            return None

        return self._download_opencast_video(element, maybe_dl)

    def _previous_contained_opencast_videos(
        self, element: IliasPageElement, element_path: PurePath
    ) -> List[PurePath]:
        if not self.prev_report:
            return []
        custom_value = self.prev_report.get_custom_value(_get_video_cache_key(element))
        if not custom_value:
            return []
        cached_value = cast(dict[str, Any], custom_value)
        if "known_paths" not in cached_value or "own_path" not in cached_value:
            log.explain(f"'known_paths' or 'own_path' missing from cached value: {cached_value}")
            return []
        transformed_own_path = self._transformer.transform(element_path)
        if cached_value["own_path"] != str(transformed_own_path):
            log.explain(
                f"own_path '{transformed_own_path}' does not match cached value: '{cached_value['own_path']}"
            )
            return []
        return [PurePath(name) for name in cached_value["known_paths"]]

    def _all_opencast_videos_locally_present(self, element: IliasPageElement, element_path: PurePath) -> bool:
        log.explain_topic(f"Checking local cache for video {fmt_path(element_path)}")
        if contained_videos := self._previous_contained_opencast_videos(element, element_path):
            log.explain(
                f"The following contained videos are known: {','.join(map(fmt_path, contained_videos))}"
            )
            if all(self._output_dir.resolve(path).exists() for path in contained_videos):
                log.explain("Found all known videos locally, skipping enumeration request")
                return True
            log.explain("Missing at least one video, continuing with requests!")
        else:
            log.explain("No local cache present")
        return False

    @anoncritical
    @_iorepeat(3, "downloading video")
    async def _download_opencast_video(self, element: IliasPageElement, dl: DownloadToken) -> None:
        def add_to_report(paths: list[str]) -> None:
            self.report.add_custom_value(
                _get_video_cache_key(element),
                {"known_paths": paths, "own_path": str(self._transformer.transform(dl.path))}
            )

        async with dl as (bar, sink):
            page = IliasPage(await self._get_page(element.url), element.url, element)
            stream_elements = page.get_child_elements()

            if len(stream_elements) > 1:
                log.explain(f"Found multiple video streams for {element.name}")
            else:
                log.explain(f"Using single video mode for {element.name}")
                stream_element = stream_elements[0]

                # We do not have a local cache yet
                await self._stream_from_url(stream_element.url, sink, bar, is_video=True)
                add_to_report([str(self._transformer.transform(dl.path))])
                return

        contained_video_paths: List[str] = []

        for stream_element in stream_elements:
            video_path = dl.path.parent / stream_element.name

            maybe_dl = await self.download(video_path, mtime=element.mtime, redownload=Redownload.NEVER)
            if not maybe_dl:
                continue
            async with maybe_dl as (bar, sink):
                log.explain(f"Streaming video from real url {stream_element.url}")
                contained_video_paths.append(str(self._transformer.transform(maybe_dl.path)))
                await self._stream_from_url(stream_element.url, sink, bar, is_video=True)

        add_to_report(contained_video_paths)

    async def _handle_file(
        self,
        element: IliasPageElement,
        element_path: PurePath,
    ) -> Optional[Coroutine[Any, Any, None]]:
        maybe_dl = await self.download(element_path, mtime=element.mtime)
        if not maybe_dl:
            return None
        return self._download_file(element, maybe_dl)

    @_iorepeat(3, "downloading file")
    @anoncritical
    async def _download_file(self, element: IliasPageElement, dl: DownloadToken) -> None:
        assert dl  # The function is only reached when dl is not None
        async with dl as (bar, sink):
            await self._stream_from_url(element.url, sink, bar, is_video=False)

    async def _stream_from_url(self, url: str, sink: FileSink, bar: ProgressBar, is_video: bool) -> None:
        async def try_stream() -> bool:
            next_url = url

            # Normal files redirect to the magazine if we are not authenticated. As files could be HTML,
            # we can not match on the content type here. Instead, we disallow redirects and inspect the
            # new location. If we are redirected anywhere but the ILIAS 8 "sendfile" command, we assume
            # our authentication expired.
            if not is_video:
                async with self.session.get(url, allow_redirects=False) as resp:
                    # Redirect to anything except a "sendfile" means we weren't authenticated
                    if hdrs.LOCATION in resp.headers:
                        if "&cmd=sendfile" not in resp.headers[hdrs.LOCATION]:
                            return False
                        # Directly follow the redirect to not make a second, unnecessary request
                        next_url = resp.headers[hdrs.LOCATION]

            # Let's try this again and follow redirects
            return await fetch_follow_redirects(next_url)

        async def fetch_follow_redirects(file_url: str) -> bool:
            async with self.session.get(file_url) as resp:
                # We wanted a video but got HTML => Forbidden, auth expired. Logging in won't really
                # solve that depending on the setup, but it is better than nothing.
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
                page = IliasPage(soup, next_stage_url, element)

                if next := page.get_next_stage_element():
                    next_stage_url = next.url
                else:
                    break

            download_data = page.get_download_forum_data()
            if not download_data:
                raise CrawlWarning("Failed to extract forum data")
            if download_data.empty:
                log.explain("Forum had no threads")
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

    async def _handle_learning_module(
        self,
        element: IliasPageElement,
        element_path: PurePath,
    ) -> Optional[Coroutine[Any, Any, None]]:
        maybe_cl = await self.crawl(element_path)
        if not maybe_cl:
            return None
        return self._crawl_learning_module(element, maybe_cl)

    @_iorepeat(3, "crawling learning module")
    @anoncritical
    async def _crawl_learning_module(self, element: IliasPageElement, cl: CrawlToken) -> None:
        elements: List[IliasLearningModulePage] = []

        async with cl:
            log.explain_topic(f"Parsing initial HTML page for {fmt_path(cl.path)}")
            log.explain(f"URL: {element.url}")
            soup = await self._get_page(element.url)
            page = IliasPage(soup, element.url, element)
            if next := page.get_learning_module_data():
                elements.extend(await self._crawl_learning_module_direction(
                    cl.path, next.previous_url, "left", element
                ))
                elements.append(next)
                elements.extend(await self._crawl_learning_module_direction(
                    cl.path, next.next_url, "right", element
                ))

        # Reflect their natural ordering in the file names
        for index, lm_element in enumerate(elements):
            lm_element.title = f"{index:02}_{lm_element.title}"

        tasks: List[Awaitable[None]] = []
        for index, elem in enumerate(elements):
            prev_url = elements[index - 1].title if index > 0 else None
            next_url = elements[index + 1].title if index < len(elements) - 1 else None
            tasks.append(asyncio.create_task(
                self._download_learning_module_page(cl.path, elem, prev_url, next_url)
            ))

        # And execute them
        await self.gather(tasks)

    async def _crawl_learning_module_direction(
        self,
        path: PurePath,
        start_url: Optional[str],
        dir: Union[Literal["left"], Literal["right"]],
        parent_element: IliasPageElement
    ) -> List[IliasLearningModulePage]:
        elements: List[IliasLearningModulePage] = []

        if not start_url:
            return elements

        next_element_url: Optional[str] = start_url
        counter = 0
        while next_element_url:
            log.explain_topic(f"Parsing HTML page for {fmt_path(path)} ({dir}-{counter})")
            log.explain(f"URL: {next_element_url}")
            soup = await self._get_page(next_element_url)
            page = IliasPage(soup, next_element_url, parent_element)
            if next := page.get_learning_module_data():
                elements.append(next)
                if dir == "left":
                    next_element_url = next.previous_url
                else:
                    next_element_url = next.next_url
            counter += 1

        return elements

    @anoncritical
    @_iorepeat(3, "saving learning module page")
    async def _download_learning_module_page(
        self,
        parent_path: PurePath,
        element: IliasLearningModulePage,
        prev: Optional[str],
        next: Optional[str]
    ) -> None:
        path = parent_path / (_sanitize_path_name(element.title) + ".html")
        maybe_dl = await self.download(path)
        if not maybe_dl:
            return
        my_path = self._transformer.transform(maybe_dl.path)
        if not my_path:
            return

        if prev:
            prev_p = self._transformer.transform(parent_path / (_sanitize_path_name(prev) + ".html"))
            if prev_p:
                prev = os.path.relpath(prev_p, my_path.parent)
            else:
                prev = None
        if next:
            next_p = self._transformer.transform(parent_path / (_sanitize_path_name(next) + ".html"))
            if next_p:
                next = os.path.relpath(next_p, my_path.parent)
            else:
                next = None

        async with maybe_dl as (bar, sink):
            content = element.content
            content = await self.internalize_images(content)
            sink.file.write(learning_module_template(content, maybe_dl.path.name, prev, next).encode("utf-8"))
            sink.done()

    async def internalize_images(self, tag: Tag) -> Tag:
        """
        Tries to fetch ILIAS images and embed them as base64 data.
        """
        log.explain_topic("Internalizing images")
        for elem in tag.find_all(recursive=True):
            if not isinstance(elem, Tag):
                continue
            if elem.name == "img":
                if src := elem.attrs.get("src", None):
                    url = urljoin(self._base_url, src)
                    if not url.startswith(self._base_url):
                        continue
                    log.explain(f"Internalizing {url!r}")
                    img = await self._get_authenticated(url)
                    elem.attrs["src"] = "data:;base64," + base64.b64encode(img).decode()
            if elem.name == "iframe" and elem.attrs.get("src", "").startswith("//"):
                # For unknown reasons the protocol seems to be stripped.
                elem.attrs["src"] = "https:" + elem.attrs["src"]
        return tag

    async def _get_page(self, url: str, root_page_allowed: bool = False) -> BeautifulSoup:
        auth_id = await self._current_auth_id()
        async with self.session.get(url) as request:
            soup = soupify(await request.read())
            if IliasPage.is_logged_in(soup):
                return self._verify_page(soup, url, root_page_allowed)

        # We weren't authenticated, so try to do that
        await self.authenticate(auth_id)

        # Retry once after authenticating. If this fails, we will die.
        async with self.session.get(url) as request:
            soup = soupify(await request.read())
            if IliasPage.is_logged_in(soup):
                return self._verify_page(soup, url, root_page_allowed)
        raise CrawlError(f"get_page failed even after authenticating on {url!r}")

    @staticmethod
    def _verify_page(soup: BeautifulSoup, url: str, root_page_allowed: bool) -> BeautifulSoup:
        if IliasPage.is_root_page(soup) and not root_page_allowed:
            raise CrawlError(
                "Unexpectedly encountered ILIAS root page. "
                "This usually happens because the ILIAS instance is broken. "
                "If so, wait a day or two and try again. "
                "It could also happen because a crawled element links to the ILIAS root page. "
                "If so, use a transform with a ! as target to ignore the particular element. "
                f"The redirect came from {url}"
            )
        return soup

    async def _post_authenticated(
        self,
        url: str,
        data: dict[str, Union[str, List[str]]]
    ) -> bytes:
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

    async def _get_authenticated(self, url: str) -> bytes:
        auth_id = await self._current_auth_id()

        async with self.session.get(url, allow_redirects=False) as request:
            if request.status == 200:
                return await request.read()

        # We weren't authenticated, so try to do that
        await self.authenticate(auth_id)

        # Retry once after authenticating. If this fails, we will die.
        async with self.session.get(url, allow_redirects=False) as request:
            if request.status == 200:
                return await request.read()
        raise CrawlError("get_authenticated failed even after authenticating")

    # ToDo: Is iorepeat still required?
    @_iorepeat(3, "Login", failure_is_error=True)
    async def _authenticate(self) -> None:
        # fill the session with the correct cookies
        params = {
            "client_id": self._client_id,
            "cmd": "force_login",
        }
        async with self.session.get(urljoin(self._base_url, "/login.php"), params=params) as request:
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
        async with self.session.post(urljoin(self._base_url, login_url), data=login_data) as request:
            soup = soupify(await request.read())
            if not self._is_logged_in(soup):
                self._auth.invalidate_credentials()

    @staticmethod
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
