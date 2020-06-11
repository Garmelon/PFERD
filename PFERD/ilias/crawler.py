"""
Contains an ILIAS crawler alongside helper functions.
"""

import datetime
import json
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from urllib.parse import (parse_qs, urlencode, urljoin, urlparse, urlsplit,
                          urlunsplit)

import bs4
import requests

from ..errors import FatalException
from ..logging import PrettyLogger
from ..utils import soupify
from .authenticators import IliasAuthenticator
from .date_demangler import demangle_date
from .downloader import IliasDownloadInfo

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


class IliasElementType(Enum):
    """
    The type of an ilias element.
    """
    REGULAR_FOLDER = "REGULAR_FOLDER"
    VIDEO_FOLDER = "VIDEO_FOLDER"
    EXERCISE_FOLDER = "EXERCISE_FOLDER"
    REGULAR_FILE = "REGULAR_FILE"
    VIDEO_FILE = "VIDEO_FILE"
    FORUM = "FORUM"
    EXTERNAL_LINK = "EXTERNAL_LINK"


IliasDirectoryFilter = Callable[[Path, IliasElementType], bool]


class IliasCrawlerEntry:
    # pylint: disable=too-few-public-methods
    """
    An ILIAS crawler entry used internally to find, catalogue and recursively crawl elements.
    """

    def __init__(
            self,
            path: Path,
            url: Union[str, Callable[[], Optional[str]]],
            entry_type: IliasElementType,
            modification_date: Optional[datetime.datetime]
    ):
        self.path = path
        if isinstance(url, str):
            str_url = url
            self.url: Callable[[], Optional[str]] = lambda: str_url
        else:
            self.url = url
        self.entry_type = entry_type
        self.modification_date = modification_date

    def to_download_info(self) -> Optional[IliasDownloadInfo]:
        """
        Converts this crawler entry to an IliasDownloadInfo, if possible.
        This method will only succeed for *File* types.
        """
        if self.entry_type in [IliasElementType.REGULAR_FILE, IliasElementType.VIDEO_FILE]:
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
            session: requests.Session,
            authenticator: IliasAuthenticator,
            dir_filter: IliasDirectoryFilter
    ):
        """
        Create a new ILIAS crawler.
        """

        self._base_url = base_url
        self._session = session
        self._authenticator = authenticator
        self.dir_filter = dir_filter

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

    def crawl_course(self, course_id: str) -> List[IliasDownloadInfo]:
        """
        Starts the crawl process for a course, yielding a list of elements to (potentially)
        download.

        Arguments:
            course_id {str} -- the course id

        Raises:
            FatalException: if an unrecoverable error occurs or the course id is not valid
        """
        # Start crawling at the given course
        root_url = self._url_set_query_param(
            self._base_url + "/goto.php", "target", f"crs_{course_id}"
        )

        if not self._is_course_id_valid(root_url, course_id):
            raise FatalException(
                "Invalid course id? The URL the server returned did not contain my id."
            )

        # And treat it as a folder
        entries: List[IliasCrawlerEntry] = self._crawl_folder(Path(""), root_url)
        return self._iterate_entries_to_download_infos(entries)

    def _is_course_id_valid(self, root_url: str, course_id: str) -> bool:
        response: requests.Response = self._session.get(root_url)
        return course_id in response.url

    def crawl_personal_desktop(self) -> List[IliasDownloadInfo]:
        """
        Crawls the ILIAS personal desktop (and every subelements that can be reached from there).

        Raises:
            FatalException: if an unrecoverable error occurs
        """
        entries: List[IliasCrawlerEntry] = self._crawl_folder(
            Path(""), self._base_url + "?baseClass=ilPersonalDesktopGUI"
        )
        return self._iterate_entries_to_download_infos(entries)

    def _iterate_entries_to_download_infos(
            self,
            entries: List[IliasCrawlerEntry]
    ) -> List[IliasDownloadInfo]:
        result: List[IliasDownloadInfo] = []
        entries_to_process: List[IliasCrawlerEntry] = entries.copy()
        while len(entries_to_process) > 0:
            entry = entries_to_process.pop()

            if entry.entry_type == IliasElementType.EXTERNAL_LINK:
                PRETTY.not_searching(entry.path, "external link")
                continue
            if entry.entry_type == IliasElementType.FORUM:
                PRETTY.not_searching(entry.path, "forum")
                continue

            if not self.dir_filter(entry.path, entry.entry_type):
                PRETTY.not_searching(entry.path, "user filter")
                continue

            download_info = entry.to_download_info()
            if download_info is not None:
                result.append(download_info)
                continue

            url = entry.url()

            if url is None:
                PRETTY.warning(f"Could not find url for {str(entry.path)!r}, skipping it")
                continue

            PRETTY.searching(entry.path)

            if entry.entry_type == IliasElementType.EXERCISE_FOLDER:
                entries_to_process += self._crawl_exercises(entry.path, url)
                continue
            if entry.entry_type == IliasElementType.REGULAR_FOLDER:
                entries_to_process += self._crawl_folder(entry.path, url)
                continue
            if entry.entry_type == IliasElementType.VIDEO_FOLDER:
                entries_to_process += self._crawl_video_directory(entry.path, url)
                continue

        return result

    def _crawl_folder(self, folder_path: Path, url: str) -> List[IliasCrawlerEntry]:
        """
        Crawl all files in a folder-like element.
        """
        soup = self._get_page(url, {})

        result: List[IliasCrawlerEntry] = []

        # Fetch all links and throw them to the general interpreter
        links: List[bs4.Tag] = soup.select("a.il_ContainerItemTitle")
        for link in links:
            abs_url = self._abs_url_from_link(link)
            element_path = Path(folder_path, link.getText().strip())
            element_type = self._find_type_from_link(element_path, link, abs_url)

            if element_type == IliasElementType.REGULAR_FILE:
                result += self._crawl_file(folder_path, link, abs_url)
            elif element_type is not None:
                result += [IliasCrawlerEntry(element_path, abs_url, element_type, None)]
            else:
                PRETTY.warning(f"Found element without a type at {str(element_path)!r}")

        return result

    def _abs_url_from_link(self, link_tag: bs4.Tag) -> str:
        """
        Create an absolute url from an <a> tag.
        """
        return urljoin(self._base_url, link_tag.get("href"))

    @staticmethod
    def _find_type_from_link(
            path: Path,
            link_element: bs4.Tag,
            url: str
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
    def _find_type_from_folder_like(link_element: bs4.Tag, url: str) -> Optional[IliasElementType]:
        """
        Try crawling something that looks like a folder.
        """
        # pylint: disable=too-many-return-statements

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
        img_tag: Optional[bs4.Tag] = found_parent.select_one("img.ilListItemIcon")

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

        return IliasElementType.REGULAR_FOLDER

    @staticmethod
    def _crawl_file(path: Path, link_element: bs4.Tag, url: str) -> List[IliasCrawlerEntry]:
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
        file_type = properties_parent.select_one("span.il_ItemProperty").getText().strip()

        # The rest does not have a stable order. Grab the whole text and reg-ex the date
        # out of it
        all_properties_text = properties_parent.getText().strip()
        modification_date_match = re.search(
            r"(((\d+\. \w+ \d+)|(Gestern|Yesterday)|(Heute|Today)|(Morgen|Tomorrow)), \d+:\d+)",
            all_properties_text
        )
        if modification_date_match is None:
            modification_date = None
            PRETTY.warning(f"Could not extract start date from {all_properties_text!r}")
        else:
            modification_date_str = modification_date_match.group(1)
            modification_date = demangle_date(modification_date_str)

        # Grab the name from the link text
        name = link_element.getText()
        full_path = Path(path, name + "." + file_type)

        return [
            IliasCrawlerEntry(full_path, url, IliasElementType.REGULAR_FILE, modification_date)
        ]

    def _crawl_video_directory(self, video_dir_path: Path, url: str) -> List[IliasCrawlerEntry]:
        """
        Crawl the video overview site.
        """
        initial_soup = self._get_page(url, {})

        # The page is actually emtpy but contains a much needed token in the link below.
        # That token can be used to fetch the *actual* video listing
        content_link: bs4.Tag = initial_soup.select_one("#tab_series a")
        # Fetch the actual video listing. The given parameters return all videos (max 800)
        # in a standalone html page
        video_list_soup = self._get_page(
            self._abs_url_from_link(content_link),
            {"limit": 800, "cmd": "asyncGetTableGUI", "cmdMode": "asynch"}
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

    def _crawl_paginated_video_directory(
            self,
            video_dir_path: Path,
            paged_video_list_soup: bs4.BeautifulSoup,
            second_stage_url: str
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
            return self._crawl_video_directory_second_stage(video_dir_path, paged_video_list_soup)

        match = re.match(r"tbl_xoct_(.+)", table_element.attrs["id"])
        if match is None:
            PRETTY.warning(
                "Could not increase elements per page (table id not found)."
                " Some might not be crawled!"
            )
            return self._crawl_video_directory_second_stage(video_dir_path, paged_video_list_soup)
        table_id = match.group(1)

        extended_video_page = self._get_page(
            second_stage_url,
            {f"tbl_xoct_{table_id}_trows": 800, "cmd": "asyncGetTableGUI", "cmdMode": "asynch"}
        )

        if self._is_paginated_video_page(extended_video_page):
            PRETTY.warning(
                "800 elements do not seem to be enough (or I failed to fetch that many)."
                " I will miss elements."
            )

        return self._crawl_video_directory_second_stage(video_dir_path, extended_video_page)

    def _crawl_video_directory_second_stage(
            self,
            video_dir_path: Path,
            video_list_soup: bs4.BeautifulSoup
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
                results += self._crawl_single_video(video_dir_path, link, False)

        return results

    def _crawl_single_video(
            self,
            parent_path: Path,
            link: bs4.Tag,
            direct_download: bool
    ) -> List[IliasCrawlerEntry]:
        """
        Crawl a single video based on its "Abspielen" link from the video listing.
        """
        # The link is part of a table with multiple columns, describing metadata.
        # 6th child (1 indexed) is the modification time string
        modification_string = link.parent.parent.parent.select_one(
            "td.std:nth-child(6)"
        ).getText().strip()
        modification_time = datetime.datetime.strptime(modification_string, "%d.%m.%Y - %H:%M")

        title = link.parent.parent.parent.select_one(
            "td.std:nth-child(3)"
        ).getText().strip()
        title += ".mp4"

        video_path: Path = Path(parent_path, title)

        video_url = self._abs_url_from_link(link)

        # The video had a direct download button we can use instead
        if direct_download:
            LOGGER.debug("Using direct download for video %r", str(video_path))
            return [IliasCrawlerEntry(
                video_path, video_url, IliasElementType.VIDEO_FILE, modification_time
            )]

        return [IliasCrawlerEntry(
            video_path,
            self._crawl_video_url_from_play_link(video_url),
            IliasElementType.VIDEO_FILE,
            modification_time
        )]

    def _crawl_video_url_from_play_link(self, play_url: str) -> Callable[[], Optional[str]]:
        def inner() -> Optional[str]:
            # Fetch the actual video page. This is a small wrapper page initializing a javscript
            # player. Sadly we can not execute that JS. The actual video stream url is nowhere
            # on the page, but defined in a JS object inside a script tag, passed to the player
            # library.
            # We do the impossible and RegEx the stream JSON object out of the page's HTML source
            video_page_soup = soupify(self._session.get(play_url))
            regex: re.Pattern = re.compile(
                r"({\"streams\"[\s\S]+?),\s*{\"paella_config_file", re.IGNORECASE
            )
            json_match = regex.search(str(video_page_soup))

            if json_match is None:
                PRETTY.warning(f"Could not find json stream info for {play_url!r}")
                return None
            json_str = json_match.group(1)

            # parse it
            json_object = json.loads(json_str)
            # and fetch the video url!
            video_url = json_object["streams"][0]["sources"]["mp4"][0]["src"]
            return video_url
        return inner

    def _crawl_exercises(self, element_path: Path, url: str) -> List[IliasCrawlerEntry]:
        """
        Crawl files offered for download in exercises.
        """
        soup = self._get_page(url, {})

        results: List[IliasCrawlerEntry] = []

        # Each assignment is in an accordion container
        assignment_containers: List[bs4.Tag] = soup.select(".il_VAccordionInnerContainer")

        for container in assignment_containers:
            # Fetch the container name out of the header to use it in the path
            container_name = container.select_one(".ilAssignmentHeader").getText().strip()
            # Find all download links in the container (this will contain all the files)
            files: List[bs4.Tag] = container.findAll(
                name="a",
                # download links contain the given command class
                attrs={"href": lambda x: x and "cmdClass=ilexsubmissiongui" in x},
                text="Download"
            )

            LOGGER.debug("Found exercise container %r", container_name)

            # Grab each file as you now have the link
            for file_link in files:
                # Two divs, side by side. Left is the name, right is the link ==> get left
                # sibling
                file_name = file_link.parent.findPrevious(name="div").getText().strip()
                url = self._abs_url_from_link(file_link)

                LOGGER.debug("Found file %r at %r", file_name, url)

                results.append(IliasCrawlerEntry(
                    Path(element_path, container_name, file_name),
                    url,
                    IliasElementType.REGULAR_FILE,
                    None  # We do not have any timestamp
                ))

        return results

    def _get_page(self, url: str, params: Dict[str, Any]) -> bs4.BeautifulSoup:
        """
        Fetches a page from ILIAS, authenticating when needed.
        """
        LOGGER.debug("Fetching %r", url)

        response = self._session.get(url, params=params)
        content_type = response.headers["content-type"]

        if not content_type.startswith("text/html"):
            raise FatalException(
                f"Invalid content type {content_type} when crawling ilias page"
                " {url!r} with {params!r}"
            )

        soup = soupify(response)

        if self._is_logged_in(soup):
            return soup

        LOGGER.info("Not authenticated, changing that...")

        self._authenticator.authenticate(self._session)

        return self._get_page(url, params)

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
            attrs={"id": lambda x: x is not None and x.startswith("tbl_xoct")}
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
