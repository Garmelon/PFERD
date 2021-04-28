"""
Contains an ILIAS crawler alongside helper functions.
"""

import datetime
import json
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable, Dict, List, Optional, Union, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlsplit, urlunsplit

import asyncio
import bs4
import httpx

from ..errors import FatalException, retry_on_io_exception
from ..logging import PrettyLogger
from ..utils import soupify
from .authenticators import IliasAuthenticator
from .date_demangler import demangle_date
from .downloader import IliasDownloadInfo

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


def _sanitize_path_name(name: str) -> str:
    return name.replace("/", "-").replace("\\", "-")


class ResultContainer:
    def __init__(self):
        self._results = []

    def add_result(self, result: IliasDownloadInfo):
        self._results.append(result)

    def get_results(self) -> List[IliasDownloadInfo]:
        return self._results


class IliasElementType(Enum):
    """
    The type of an ilias element.
    """

    COURSE = "COURSE"
    REGULAR_FOLDER = "REGULAR_FOLDER"
    VIDEO_FOLDER = "VIDEO_FOLDER"
    EXERCISE_FOLDER = "EXERCISE_FOLDER"
    REGULAR_FILE = "REGULAR_FILE"
    VIDEO_FILE = "VIDEO_FILE"
    FORUM = "FORUM"
    MEETING = "MEETING"
    EXTERNAL_LINK = "EXTERNAL_LINK"

    def is_folder(self) -> bool:
        """
        Returns whether this type is some kind of folder.
        """
        return "FOLDER" in str(self.name)


IliasDirectoryFilter = Callable[[Path, IliasElementType], bool]


class InvalidCourseError(FatalException):
    """
    A invalid Course ID was encountered
    """

    def __init__(course_id: str):
        super(
            f"Invalid course id {course_id}? I didn't find anything looking like a course!"
        )


class IliasCrawlerEntry:
    # pylint: disable=too-few-public-methods
    """
    An ILIAS crawler entry used internally to find, catalogue and recursively crawl elements.
    """

    def __init__(
        self,
        path: Path,
        url: Union[str, Callable[[], Awaitable[Optional[str]]]],
        entry_type: IliasElementType,
        modification_date: Optional[datetime.datetime],
    ):
        self.path = path
        if isinstance(url, str):
            future = asyncio.Future()
            future.set_result(url)
            self.url: Callable[[], Awaitable[Optional[str]]] = lambda: future
        else:
            self.url = url
        self.entry_type = entry_type
        self.modification_date = modification_date

    def to_download_info(self) -> Optional[IliasDownloadInfo]:
        """
        Converts this crawler entry to an IliasDownloadInfo, if possible.
        This method will only succeed for *File* types.
        """
        if self.entry_type in [
            IliasElementType.REGULAR_FILE,
            IliasElementType.VIDEO_FILE,
        ]:
            return IliasDownloadInfo(self.path, self.url, self.modification_date)
        return None


class IliasCrawler:
    # pylint: disable=too-few-public-methods

    """
    A crawler for ILIAS.
    """

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient,
        authenticator: IliasAuthenticator,
        dir_filter: IliasDirectoryFilter,
    ):
        """
        Create a new ILIAS crawler.
        Warning: This will create syncronization primitives
                 that are tied to the currently running event
                 loop. This means you cant use asyncio.run but
                 will need to use run_until_completion when using
                 methodes.
        """
        self._base_url = base_url
        self._client = client
        self._authenticator = authenticator
        self.dir_filter = dir_filter

        # Setup authentication locks
        self.auth_event = asyncio.Event()
        self.auth_lock = asyncio.Lock()

    @staticmethod
    def _url_set_query_param(url: str, param: str, value: str) -> str:
        """
        Set a query parameter in an url, overwriting existing ones with the same name.
        """
        scheme, netloc, path, query, fragment = urlsplit(url)
        query_parameters = parse_qs(query)
        query_parameters[param] = [value]
        new_query_string = urlencode(query_parameters, doseq=True)

        return urlunsplit((scheme, netloc, path, new_query_string, fragment))

    async def recursive_crawl_url(self, url: str) -> IliasCrawlerEntry:
        """
        Creates a crawl target for a given url *and all reachable elements in it*.

        Args:
            url {str} -- the *full* url to crawl
        """

        return IliasCrawlerEntry(Path(""), url, IliasElementType.REGULAR_FOLDER, None)

    async def crawl_course(self, course_id: str) -> IliasCrawlerEntry:
        """
        Creates a crawl target for a course, yielding a list of elements to (potentially)
        download.

        Arguments:
            course_id {str} -- the course id

        """
        # Start crawling at the given course
        root_url = self._url_set_query_param(
            self._base_url + "/goto.php", "target", f"crs_{course_id}"
        )

        return IliasCrawlerEntry(Path(""), root_url, IliasElementType.COURSE, None)

    async def find_course_name(self, course_id: str) -> Optional[str]:
        """
        Returns the name of a given course. None if it is not a valid course
        or it could not be found.
        """
        course_url = self._url_set_query_param(
            self._base_url + "/goto.php", "target", f"crs_{course_id}"
        )
        return await self.find_element_name(course_url)

    async def find_element_name(self, url: str) -> Optional[str]:
        """
        Returns the name of the element at the given URL, if it can find one.
        """
        focus_element: bs4.Tag = (await self._get_page(url, {})).find(
            id="il_mhead_t_focus"
        )
        if not focus_element:
            return None
        return focus_element.text

    async def crawl_personal_desktop(self) -> IliasCrawlerEntry:
        """
        Creates a crawl target for the ILIAS personal desktop (and every subelements that can be reached from there).
        download.
        """
        return IliasCrawlerEntry(
            Path(""),
            self._base_url + "?baseClass=ilPersonalDesktopGUI",
            IliasElementType.REGULAR_FOLDER,
            None,
        )

    async def _crawl_worker(self, entries_to_process: asyncio.Queue):
        while True:
            (entry, results) = await entries_to_process.get()

            if entry.entry_type == IliasElementType.EXTERNAL_LINK:
                PRETTY.not_searching(entry.path, "external link")
                entries_to_process.task_done()
                continue
            if entry.entry_type == IliasElementType.FORUM:
                PRETTY.not_searching(entry.path, "forum")
                entries_to_process.task_done()
                continue

            if entry.entry_type.is_folder() and not self.dir_filter(
                entry.path, entry.entry_type
            ):
                PRETTY.not_searching(entry.path, "user filter")
                entries_to_process.task_done()
                continue

            download_info = entry.to_download_info()
            if download_info is not None:
                results.add_result(download_info)
                entries_to_process.task_done()
                continue

            url = await entry.url()

            if url is None:
                PRETTY.warning(
                    f"Could not find url for {str(entry.path)!r}, skipping it"
                )
                entries_to_process.task_done()
                continue

            PRETTY.searching(entry.path)

            if entry.entry_type == IliasElementType.EXERCISE_FOLDER:
                for task in await self._crawl_exercises(entry.path, url):
                    entries_to_process.put_nowait((task, results))
                entries_to_process.task_done()
                continue
            if entry.entry_type == IliasElementType.REGULAR_FOLDER:
                for task in await self._crawl_folder(entry.path, url):
                    entries_to_process.put_nowait((task, results))
                entries_to_process.task_done()
                continue
            if entry.entry_type == IliasElementType.COURSE:
                for task in await self._crawl_folder(
                    entry.path, url, url.split("crs_")[1]
                ):
                    entries_to_process.put_nowait((task, results))
                entries_to_process.task_done()
                continue
            if entry.entry_type == IliasElementType.VIDEO_FOLDER:
                for task in await self._crawl_video_directory(entry.path, url):
                    entries_to_process.put_nowait((task, results))
                entries_to_process.task_done()
                continue

            PRETTY.warning(f"Unknown type: {entry.entry_type}!")

    async def iterate_entries_to_download_infos(
        self, entries: List[Tuple[IliasCrawlerEntry, ResultContainer]]
    ):
        crawl_queue = asyncio.Queue()

        for entry in entries:
            crawl_queue.put_nowait(entry)

        workers = []

        # TODO: Find proper worker limit
        for _ in range(20):
            worker = asyncio.create_task(self._crawl_worker(crawl_queue))
            workers.append(worker)

        await crawl_queue.join()

        for worker in workers:
            worker.cancel()

        # Wait until all worker tasks are cancelled.
        await asyncio.gather(*workers, return_exceptions=True)

    async def _crawl_folder(
        self, folder_path: Path, url: str, course: Optional[str] = None
    ) -> List[IliasCrawlerEntry]:
        """
        Crawl all files in a folder-like element.

        Raises a InvalidCourseError if the folder is a non existent course.
        """
        soup = await self._get_page(url, {}, check_course_id_valid=course)

        if course is not None:
            link_element: bs4.Tag = soup.find(id="current_perma_link")
            # It wasn't a course but a category list, forum, etc.
            if not link_element or "crs_" not in link_element.get("value"):
                raise InvalidCourseError(course)

        if soup.find(id="headerimage"):
            element: bs4.Tag = soup.find(id="headerimage")
            if "opencast" in element.attrs["src"].lower():
                PRETTY.warning(
                    f"Switched to crawling a video at {folder_path}")
                if not self.dir_filter(folder_path, IliasElementType.VIDEO_FOLDER):
                    PRETTY.not_searching(folder_path, "user filter")
                    return []
                return self._crawl_video_directory(folder_path, url)

        result: List[IliasCrawlerEntry] = []

        # Fetch all links and throw them to the general interpreter
        links: List[bs4.Tag] = soup.select("a.il_ContainerItemTitle")
        for link in links:
            abs_url = self._abs_url_from_link(link)
            element_path = Path(
                folder_path, _sanitize_path_name(link.getText().strip())
            )
            element_type = self._find_type_from_link(
                element_path, link, abs_url)

            if element_type == IliasElementType.REGULAR_FILE:
                result += self._crawl_file(folder_path, link, abs_url)
            elif element_type == IliasElementType.MEETING:
                meeting_name = str(element_path.name)
                date_portion_str = meeting_name.split(" - ")[0]
                date_portion = demangle_date(date_portion_str)

                if not date_portion:
                    result += [
                        IliasCrawlerEntry(
                            element_path, abs_url, element_type, None)
                    ]
                    continue

                rest_of_name = meeting_name
                if rest_of_name.startswith(date_portion_str):
                    rest_of_name = rest_of_name[len(date_portion_str):]

                new_name = (
                    datetime.datetime.strftime(date_portion, "%Y-%m-%d, %H:%M")
                    + rest_of_name
                )
                new_path = Path(folder_path, _sanitize_path_name(new_name))
                result += [
                    IliasCrawlerEntry(
                        new_path, abs_url, IliasElementType.REGULAR_FOLDER, None
                    )
                ]
            elif element_type is not None:
                result += [IliasCrawlerEntry(element_path,
                                             abs_url, element_type, None)]
            else:
                PRETTY.warning(
                    f"Found element without a type at {str(element_path)!r}")

        return result

    def _abs_url_from_link(self, link_tag: bs4.Tag) -> str:
        """
        Create an absolute url from an <a> tag.
        """
        return urljoin(self._base_url, link_tag.get("href"))

    @staticmethod
    def _find_type_from_link(
        path: Path, link_element: bs4.Tag, url: str
    ) -> Optional[IliasElementType]:
        """
        Decides which sub crawler to use for a given top level element.
        """
        parsed_url = urlparse(url)
        LOGGER.debug("Parsed url: %r", parsed_url)

        # file URLs contain "target=file"
        if "target=file_" in parsed_url.query:
            return IliasElementType.REGULAR_FILE

        # Skip forums
        if "cmd=showThreads" in parsed_url.query:
            return IliasElementType.FORUM

        # Everything with a ref_id can *probably* be opened to reveal nested things
        # video groups, directories, exercises, etc
        if "ref_id=" in parsed_url.query:
            return IliasCrawler._find_type_from_folder_like(link_element, url)

        PRETTY.warning(
            "Got unknown element type in switch. I am not sure what horror I found on the"
            f" ILIAS page. The element was at {str(path)!r} and it is {link_element!r})"
        )
        return None

    @staticmethod
    def _find_type_from_folder_like(
        link_element: bs4.Tag, url: str
    ) -> Optional[IliasElementType]:
        """
        Try crawling something that looks like a folder.
        """
        # pylint: disable=too-many-return-statements

        found_parent: Optional[bs4.Tag] = None

        # We look for the outer div of our inner link, to find information around it
        # (mostly the icon)
        for parent in link_element.parents:
            if "ilContainerListItemOuter" in parent["class"]:
                found_parent = parent
                break

        if found_parent is None:
            PRETTY.warning(f"Could not find element icon for {url!r}")
            return None

        # Find the small descriptive icon to figure out the type
        img_tag: Optional[bs4.Tag] = found_parent.select_one(
            "img.ilListItemIcon")

        if img_tag is None:
            PRETTY.warning(f"Could not find image tag for {url!r}")
            return None

        if "opencast" in str(img_tag["alt"]).lower():
            return IliasElementType.VIDEO_FOLDER

        if str(img_tag["src"]).endswith("icon_exc.svg"):
            return IliasElementType.EXERCISE_FOLDER

        if str(img_tag["src"]).endswith("icon_webr.svg"):
            return IliasElementType.EXTERNAL_LINK

        if str(img_tag["src"]).endswith("frm.svg"):
            return IliasElementType.FORUM

        if str(img_tag["src"]).endswith("sess.svg"):
            return IliasElementType.MEETING

        return IliasElementType.REGULAR_FOLDER

    @staticmethod
    def _crawl_file(
        path: Path, link_element: bs4.Tag, url: str
    ) -> List[IliasCrawlerEntry]:
        """
        Crawls a file.
        """
        # Files have a list of properties (type, modification date, size, etc.)
        # In a series of divs.
        # Find the parent containing all those divs, so we can filter our what we need
        properties_parent: bs4.Tag = link_element.findParent(
            "div", {"class": lambda x: "il_ContainerListItem" in x}
        ).select_one(".il_ItemProperties")
        # The first one is always the filetype
        file_type = (
            properties_parent.select_one(
                "span.il_ItemProperty").getText().strip()
        )

        # The rest does not have a stable order. Grab the whole text and reg-ex the date
        # out of it
        all_properties_text = properties_parent.getText().strip()
        modification_date_match = re.search(
            r"(((\d+\. \w+ \d+)|(Gestern|Yesterday)|(Heute|Today)|(Morgen|Tomorrow)), \d+:\d+)",
            all_properties_text,
        )
        if modification_date_match is None:
            modification_date = None
            PRETTY.warning(
                f"Could not extract start date from {all_properties_text!r}")
        else:
            modification_date_str = modification_date_match.group(1)
            modification_date = demangle_date(modification_date_str)

        # Grab the name from the link text
        name = _sanitize_path_name(link_element.getText())
        full_path = Path(path, name + "." + file_type)

        return [
            IliasCrawlerEntry(
                full_path, url, IliasElementType.REGULAR_FILE, modification_date
            )
        ]

    async def _crawl_video_directory(
        self, video_dir_path: Path, url: str
    ) -> List[IliasCrawlerEntry]:
        """
        Crawl the video overview site.
        """
        initial_soup = await self._get_page(url, {})

        # The page is actually emtpy but contains a much needed token in the link below.
        # That token can be used to fetch the *actual* video listing
        content_link: bs4.Tag = initial_soup.select_one("#tab_series a")
        # Fetch the actual video listing. The given parameters return all videos (max 800)
        # in a standalone html page
        video_list_soup = await self._get_page(
            self._abs_url_from_link(content_link),
            {"limit": 800, "cmd": "asyncGetTableGUI", "cmdMode": "asynch"},
        )

        # If we find a page selected, we probably need to respect pagination
        if self._is_paginated_video_page(video_list_soup):
            second_stage_url = self._abs_url_from_link(content_link)

            return self._crawl_paginated_video_directory(
                video_dir_path, video_list_soup, second_stage_url
            )

        return self._crawl_video_directory_second_stage(video_dir_path, video_list_soup)

    @staticmethod
    def _is_paginated_video_page(soup: bs4.BeautifulSoup) -> bool:
        return soup.find(id=re.compile(r"tab_page_sel.+")) is not None

    async def _crawl_paginated_video_directory(
        self,
        video_dir_path: Path,
        paged_video_list_soup: bs4.BeautifulSoup,
        second_stage_url: str,
    ) -> List[IliasCrawlerEntry]:
        LOGGER.info("Found paginated video page, trying 800 elements")

        # Try to find the table id. This can be used to build the query parameter indicating
        # you want 800 elements

        table_element: bs4.Tag = paged_video_list_soup.find(
            name="table", id=re.compile(r"tbl_xoct_.+")
        )
        if table_element is None:
            PRETTY.warning(
                "Could not increase elements per page (table not found)."
                " Some might not be crawled!"
            )
            return self._crawl_video_directory_second_stage(
                video_dir_path, paged_video_list_soup
            )

        match = re.match(r"tbl_xoct_(.+)", table_element.attrs["id"])
        if match is None:
            PRETTY.warning(
                "Could not increase elements per page (table id not found)."
                " Some might not be crawled!"
            )
            return self._crawl_video_directory_second_stage(
                video_dir_path, paged_video_list_soup
            )
        table_id = match.group(1)

        extended_video_page = await self._get_page(
            second_stage_url,
            {
                f"tbl_xoct_{table_id}_trows": 800,
                "cmd": "asyncGetTableGUI",
                "cmdMode": "asynch",
            },
        )

        if self._is_paginated_video_page(extended_video_page):
            PRETTY.warning(
                "800 elements do not seem to be enough (or I failed to fetch that many)."
                " I will miss elements."
            )

        return self._crawl_video_directory_second_stage(
            video_dir_path, extended_video_page
        )

    def _crawl_video_directory_second_stage(
        self, video_dir_path: Path, video_list_soup: bs4.BeautifulSoup
    ) -> List[IliasCrawlerEntry]:
        """
        Crawls the "second stage" video page. This page contains the actual video urls.
        """
        direct_download_links: List[bs4.Tag] = video_list_soup.findAll(
            name="a", text=re.compile(r"\s*Download\s*")
        )

        # Video start links are marked with an "Abspielen" link
        video_links: List[bs4.Tag] = video_list_soup.findAll(
            name="a", text=re.compile(r"\s*Abspielen\s*")
        )

        results: List[IliasCrawlerEntry] = []

        # We can download everything directly!
        # FIXME: Sadly the download button is currently broken, so never do that
        if False and len(direct_download_links) == len(video_links):
            for link in direct_download_links:
                results += self._crawl_single_video(video_dir_path, link, True)
        else:
            for link in video_links:
                results += self._crawl_single_video(
                    video_dir_path, link, False)

        return results

    def _crawl_single_video(
        self, parent_path: Path, link: bs4.Tag, direct_download: bool
    ) -> List[IliasCrawlerEntry]:
        """
        Crawl a single video based on its "Abspielen" link from the video listing.
        """
        # The link is part of a table with multiple columns, describing metadata.
        # 6th child (1 indexed) is the modification time string
        modification_string = (
            link.parent.parent.parent.select_one("td.std:nth-child(6)")
            .getText()
            .strip()
        )
        modification_time = datetime.datetime.strptime(
            modification_string, "%d.%m.%Y - %H:%M"
        )

        title = (
            link.parent.parent.parent.select_one("td.std:nth-child(3)")
            .getText()
            .strip()
        )
        title += ".mp4"

        video_path: Path = Path(parent_path, _sanitize_path_name(title))

        video_url = self._abs_url_from_link(link)

        # The video had a direct download button we can use instead
        if direct_download:
            LOGGER.debug("Using direct download for video %r", str(video_path))
            return [
                IliasCrawlerEntry(
                    video_path,
                    video_url,
                    IliasElementType.VIDEO_FILE,
                    modification_time,
                )
            ]

        return [
            IliasCrawlerEntry(
                video_path,
                self._crawl_video_url_from_play_link(video_url),
                IliasElementType.VIDEO_FILE,
                modification_time,
            )
        ]

    def _crawl_video_url_from_play_link(
        self, play_url: str
    ) -> Callable[[], Awaitable[Optional[str]]]:
        async def inner() -> Optional[str]:
            # Fetch the actual video page. This is a small wrapper page initializing a javscript
            # player. Sadly we can not execute that JS. The actual video stream url is nowhere
            # on the page, but defined in a JS object inside a script tag, passed to the player
            # library.
            # We do the impossible and RegEx the stream JSON object out of the page's HTML source
            video_page_soup = soupify(await self._client.get(play_url))
            regex: re.Pattern = re.compile(
                r"({\"streams\"[\s\S]+?),\s*{\"paella_config_file", re.IGNORECASE
            )
            json_match = regex.search(str(video_page_soup))

            if json_match is None:
                PRETTY.warning(
                    f"Could not find json stream info for {play_url!r}")
                return None
            json_str = json_match.group(1)

            # parse it
            json_object = json.loads(json_str)
            # and fetch the video url!
            video_url = json_object["streams"][0]["sources"]["mp4"][0]["src"]
            return video_url

        return inner

    async def _crawl_exercises(
        self, element_path: Path, url: str
    ) -> List[IliasCrawlerEntry]:
        """
        Crawl files offered for download in exercises.
        """
        soup = await self._get_page(url, {})

        results: List[IliasCrawlerEntry] = []

        # Each assignment is in an accordion container
        assignment_containers: List[bs4.Tag] = soup.select(
            ".il_VAccordionInnerContainer"
        )

        for container in assignment_containers:
            # Fetch the container name out of the header to use it in the path
            container_name = (
                container.select_one(".ilAssignmentHeader").getText().strip()
            )
            # Find all download links in the container (this will contain all the files)
            files: List[bs4.Tag] = container.findAll(
                name="a",
                # download links contain the given command class
                attrs={"href": lambda x: x and "cmdClass=ilexsubmissiongui" in x},
                text="Download",
            )

            LOGGER.debug("Found exercise container %r", container_name)

            # Grab each file as you now have the link
            for file_link in files:
                # Two divs, side by side. Left is the name, right is the link ==> get left
                # sibling
                file_name = file_link.parent.findPrevious(
                    name="div").getText().strip()
                file_name = _sanitize_path_name(file_name)
                url = self._abs_url_from_link(file_link)

                LOGGER.debug("Found file %r at %r", file_name, url)

                results.append(
                    IliasCrawlerEntry(
                        Path(element_path, container_name, file_name),
                        url,
                        IliasElementType.REGULAR_FILE,
                        None,  # We do not have any timestamp
                    )
                )

        return results

    @retry_on_io_exception(3, "fetching webpage")
    async def _get_page(
        self,
        url: str,
        params: Dict[str, Any],
        retry_count: int = 0,
        check_course_id_valid: Optional[str] = None,
    ) -> bs4.BeautifulSoup:
        """
        Fetches a page from ILIAS, authenticating when needed.

        Raises a InvalidCourseError if the page is a non existent course.
        """

        if retry_count >= 4:
            raise FatalException(
                "Could not get a proper page after 4 tries. "
                "Maybe your URL is wrong, authentication fails continuously, "
                "your ILIAS connection is spotty or ILIAS is not well."
            )

        LOGGER.debug("Fetching %r", url)

        response = await self._client.get(url, params=params)

        if check_course_id_valid is not None:
            # We were redirected ==> Non-existant ID
            if check_course_id_valid not in str(response.url):
                raise InvalidCourseError(check_course_id_valid)

        content_type = response.headers["content-type"]

        if not content_type.startswith("text/html"):
            raise FatalException(
                f"Invalid content type {content_type} when crawling ilias page"
                " {url!r} with {params!r}"
            )

        soup = soupify(response)

        if self._is_logged_in(soup):
            return soup

        if self.auth_lock.locked():
            # Some other future is already logging in
            await self.auth_event.wait()
        else:
            await self.auth_lock.acquire()
            self.auth_event.clear()
            LOGGER.info("Not authenticated, changing that...")
            await self._authenticator.authenticate(self._client)
            self.auth_event.set()
            self.auth_lock.release()

        return await self._get_page(
            url,
            params,
            check_course_id_valid=check_course_id_valid,
            retry_count=retry_count + 1,
        )

    @staticmethod
    def _is_logged_in(soup: bs4.BeautifulSoup) -> bool:
        # Normal ILIAS pages
        userlog = soup.find("li", {"id": "userlog"})
        if userlog is not None:
            LOGGER.debug("Auth: Found #userlog")
            return True
        # Video listing embeds do not have complete ILIAS html. Try to match them by
        # their video listing table
        video_table = soup.find(
            recursive=True,
            name="table",
            attrs={"id": lambda x: x is not None and x.startswith("tbl_xoct")},
        )
        if video_table is not None:
            LOGGER.debug("Auth: Found #tbl_xoct.+")
            return True
        # The individual video player wrapper page has nothing of the above.
        # Match it by its playerContainer.
        if soup.select_one("#playerContainer") is not None:
            LOGGER.debug("Auth: Found #playerContainer")
            return True
        return False
