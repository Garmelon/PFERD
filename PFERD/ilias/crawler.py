"""
Contains an ILIAS crawler alongside helper functions.
"""

import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import (parse_qs, urlencode, urljoin, urlparse, urlsplit,
                          urlunsplit)

import bs4
import requests

from ..logging import FatalException, PrettyLogger
from ..utils import soupify
from .authenticators import IliasAuthenticator
from .date_demangler import demangle_date
from .downloader import IliasDownloadInfo

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)

IliasDirectoryFilter = Callable[[Path], bool]


class IliasCrawler:
    # pylint: disable=too-few-public-methods

    """
    A crawler for ILIAS.
    """

    # pylint: disable=too-many-arguments
    def __init__(
            self,
            base_url: str,
            course_id: str,
            session: requests.Session,
            authenticator: IliasAuthenticator,
            dir_filter: IliasDirectoryFilter
    ):
        """
        Create a new ILIAS crawler.
        """

        self._base_url = base_url
        self._course_id = course_id
        self._session = session
        self._authenticator = authenticator
        self.dir_filter = dir_filter

    def _abs_url_from_link(self, link_tag: bs4.Tag) -> str:
        """
        Create an absolute url from an <a> tag.
        """
        return urljoin(self._base_url, link_tag.get("href"))

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

    def crawl(self) -> List[IliasDownloadInfo]:
        """
        Starts the crawl process, yielding a list of elements to (potentially) download.
        """

        # Start crawling at the given course
        root_url = self._url_set_query_param(
            self._base_url + "/goto.php", "target", f"crs_{self._course_id}"
        )

        if not self._is_course_id_valid(root_url):
            raise FatalException(
                "Invalid course id? The URL the server returned did not contain my id."
            )

        # And treat it as a folder
        return self._crawl_folder(Path(""), root_url)

    def _is_course_id_valid(self, root_url: str) -> bool:
        response: requests.Response = self._session.get(root_url)
        return self._course_id in response.url

    def _switch_on_crawled_type(
            self,
            path: Path,
            link_element: bs4.Tag,
            url: str
    ) -> List[IliasDownloadInfo]:
        """
        Decides which sub crawler to use for a given top level element.
        """
        parsed_url = urlparse(url)
        LOGGER.debug("Parsed url: %r", parsed_url)

        # file URLs contain "target=file"
        if "target=file_" in parsed_url.query:
            LOGGER.debug("Interpreted as file.")
            return self._crawl_file(path, link_element, url)

        # Skip forums
        if "cmd=showThreads" in parsed_url.query:
            LOGGER.debug("Skipping forum %r", url)
            return []

        # Everything with a ref_id can *probably* be opened to reveal nested things
        # video groups, directories, exercises, etc
        if "ref_id=" in parsed_url.query:
            LOGGER.debug("Processing folder-like...")
            return self._switch_on_folder_like(path, link_element, url)

        PRETTY.warning(
            "Got unkwarning element type in switch. I am not sure what horror I found on the"
            f" ILIAS page. The element was at {str(path)!r} and it is {link_element!r})"
        )
        return []

    @staticmethod
    def _crawl_file(path: Path, link_element: bs4.Tag, url: str) -> List[IliasDownloadInfo]:
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
            LOGGER.warning("Could not extract start date from %r", all_properties_text)
        else:
            modification_date_str = modification_date_match.group(1)
            modification_date = demangle_date(modification_date_str)

        # Grab the name from the link text
        name = link_element.getText()
        full_path = Path(path, name + "." + file_type)

        return [IliasDownloadInfo(full_path, url, modification_date)]

    def _switch_on_folder_like(
            self,
            parent_path: Path,
            link_element: bs4.Tag,
            url: str
    ) -> List[IliasDownloadInfo]:
        """
        Try crawling something that looks like a folder.
        """
        # pylint: disable=too-many-return-statements

        element_path = Path(parent_path, link_element.getText().strip())

        if not self.dir_filter(element_path):
            PRETTY.not_searching(element_path, "user filter")
            return []

        PRETTY.searching(element_path)

        found_parent: Optional[bs4.Tag] = None

        # We look for the outer div of our inner link, to find information around it
        # (mostly the icon)
        for parent in link_element.parents:
            if "ilContainerListItemOuter" in parent["class"]:
                found_parent = parent
                break

        if found_parent is None:
            LOGGER.warning("Could not find element icon for %r", url)
            return []

        # Find the small descriptive icon to figure out the type
        img_tag: Optional[bs4.Tag] = found_parent.select_one("img.ilListItemIcon")

        if img_tag is None:
            LOGGER.warning("Could not find image tag for %r", url)
            return []

        # A forum
        if str(img_tag["src"]).endswith("frm.svg"):
            LOGGER.debug("Skipping forum at %r", url)
            PRETTY.not_searching(element_path, "forum")
            return []

        # An exercise
        if str(img_tag["src"]).endswith("icon_exc.svg"):
            LOGGER.debug("Crawling exercises at %r", url)
            return self._crawl_exercises(element_path, url)

        if str(img_tag["src"]).endswith("icon_webr.svg"):
            LOGGER.debug("Skipping external link at %r", url)
            PRETTY.not_searching(element_path, "external link")
            return []

        # Match the opencast video plugin
        if "opencast" in str(img_tag["alt"]).lower():
            LOGGER.debug("Found video site: %r", url)
            return self._crawl_video_directory(element_path, url)

        # Assume it is a folder
        return self._crawl_folder(element_path, self._abs_url_from_link(link_element))

    def _crawl_video_directory(self, video_dir_path: Path, url: str) -> List[IliasDownloadInfo]:
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

        direct_download_links: List[bs4.Tag] = video_list_soup.findAll(
            name="a", text=re.compile(r"\s*Download\s*")
        )

        # Video start links are marked with an "Abspielen" link
        video_links: List[bs4.Tag] = video_list_soup.findAll(
            name="a", text=re.compile(r"\s*Abspielen\s*")
        )

        results: List[IliasDownloadInfo] = []

        # We can download everything directly!
        if len(direct_download_links) == len(video_links):
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
    ) -> List[IliasDownloadInfo]:
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

        # The video had a direct download button we can use instead
        if direct_download:
            LOGGER.debug("Using direct download for video %r", str(video_path))
            return [IliasDownloadInfo(
                video_path,
                self._abs_url_from_link(link),
                modification_time
            )]

        # Fetch the actual video page. This is a small wrapper page initializing a javscript
        # player. Sadly we can not execute that JS. The actual video stream url is nowhere
        # on the page, but defined in a JS object inside a script tag, passed to the player
        # library.
        # We do the impossible and RegEx the stream JSON object out of the page's HTML source
        video_page_url = self._abs_url_from_link(link)
        video_page_soup = self._get_page(video_page_url, {})
        regex: re.Pattern = re.compile(
            r"({\"streams\"[\s\S]+?),\s*{\"paella_config_file", re.IGNORECASE
        )
        json_match = regex.search(str(video_page_soup))

        if json_match is None:
            LOGGER.warning("Could not find json stream info for %r", video_page_url)
            return []
        json_str = json_match.group(1)

        # parse it
        json_object = json.loads(json_str)
        # and fetch the video url!
        video_url = json_object["streams"][0]["sources"]["mp4"][0]["src"]

        return [IliasDownloadInfo(video_path, video_url, modification_time)]

    def _crawl_exercises(self, element_path: Path, url: str) -> List[IliasDownloadInfo]:
        """
        Crawl files offered for download in exercises.
        """
        soup = self._get_page(url, {})

        results: List[IliasDownloadInfo] = []

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

                results.append(IliasDownloadInfo(
                    Path(element_path, container_name, file_name),
                    url,
                    None  # We do not have any timestamp
                ))

        return results

    def _crawl_folder(self, folder_path: Path, url: str) -> List[IliasDownloadInfo]:
        """
        Crawl all files in a folder-like element.
        """
        soup = self._get_page(url, {})

        result: List[IliasDownloadInfo] = []

        # Fetch all links and throw them to the general interpreter
        links: List[bs4.Tag] = soup.select("a.il_ContainerItemTitle")
        for link in links:
            abs_url = self._abs_url_from_link(link)
            result += self._switch_on_crawled_type(folder_path, link, abs_url)

        return result

    def _get_page(self, url: str, params: Dict[str, Any]) -> bs4.BeautifulSoup:
        """
        Fetches a page from ILIAS, authenticating when needed.
        """
        LOGGER.debug("Fetching %r", url)

        response = self._session.get(url, params=params)
        content_type = response.headers["content-type"]

        if not content_type.startswith("text/html"):
            # TODO: Correct exception type
            raise Exception(f"Invalid content type {content_type}")

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
