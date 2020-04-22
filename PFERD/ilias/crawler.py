"""
Contains an ILIAS crawler alongside helper functions.
"""

import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import (parse_qs, urlencode, urljoin, urlparse, urlsplit,
                          urlunsplit)

import bs4

from ..cookie_jar import CookieJar
from ..utils import soupify
from .authenticators import IliasAuthenticator
from .date_demangler import demangle_date
from .downloader import IliasDownloadInfo

LOGGER = logging.getLogger(__name__)


class IliasCrawler:
    # pylint: disable=too-few-public-methods
    """
    A crawler for ILIAS.
    """

    def __init__(self, authenticator: IliasAuthenticator, base_url: str, course_id: str):
        """
        Create a new ILIAS crawler.
        """
        self._cookie_jar = CookieJar(Path("/tmp/test/cookies"))
        self._cookie_jar.load_cookies()

        self._base_url = base_url
        self._course_id = course_id
        self._session = self._cookie_jar.create_session()
        self._authenticator = authenticator

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

        # And treat it as a folder
        return self._crawl_folder(Path(""), root_url)

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

        LOGGER.warning("Got unknown type, %r, %r, %r", path, link_element, url)
        # TODO: Other types
        raise Exception("Implement me!")

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
            r"(((\d+\. \w+ \d+)|(Gestern)|(Heute)), \d+:\d+)",
            all_properties_text
        )
        if modification_date_match is None:
            modification_date = datetime.datetime.now()
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
            path: Path,
            link_element: bs4.Tag,
            url: str
    ) -> List[IliasDownloadInfo]:
        """
        Try crawling something that looks like a folder.
        """
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
            return []

        element_path = Path(path, link_element.getText().strip())

        # An exercise
        if str(img_tag["src"]).endswith("icon_exc.svg"):
            LOGGER.debug("Crawling exercises at %r", url)
            return self._crawl_exercises(element_path, url)

        # Match the opencast video plugin
        if "opencast" in str(img_tag["alt"]).lower():
            LOGGER.debug("Found video site: %r", url)
            return self._crawl_video_directory(element_path, url)

        # Assume it is a folder
        return self._crawl_folder(element_path, self._abs_url_from_link(link_element))

    def _crawl_video_directory(self, path: Path, url: str) -> List[IliasDownloadInfo]:
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

        # Video start links are marked with an "Abspielen" link
        video_links: List[bs4.Tag] = video_list_soup.findAll(
            name="a", text=re.compile(r"\s*Abspielen\s*")
        )

        results: List[IliasDownloadInfo] = []

        for link in video_links:
            results += self._crawl_single_video(path, link)

        return results

    def _crawl_single_video(self, path: Path, link: bs4.Tag) -> List[IliasDownloadInfo]:
        """
        Crawl a single video based on its "Abspielen" link from the video listing.
        """
        video_page_url = self._abs_url_from_link(link)

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

        # Fetch the actual video page. This is a small wrapper page initializing a javscript
        # player. Sadly we can not execute that JS. The actual video stream url is nowhere
        # on the page, but defined in a JS object inside a script tag, passed to the player
        # library.
        # We do the impossible and RegEx the stream JSON object out of the page's HTML source
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

        return [IliasDownloadInfo(Path(path, title), video_url, modification_time)]

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

            # Parse the end date to use as modification date
            # TODO: Return None?
            end_date: datetime.datetime = datetime.datetime.now()
            end_date_header: bs4.Tag = container.find(name="div", text="Abgabetermin")
            if end_date_header is not None:
                end_date_text = end_date_header.findNext("div").getText().strip()
                end_date = demangle_date(end_date_text)

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
                    end_date
                ))

        return results

    def _crawl_folder(self, path: Path, url: str) -> List[IliasDownloadInfo]:
        """
        Crawl all files in a folder-like element.
        """
        soup = self._get_page(url, {})

        result: List[IliasDownloadInfo] = []

        # Fetch all links and throw them to the general interpreter
        links: List[bs4.Tag] = soup.select("a.il_ContainerItemTitle")
        for link in links:
            abs_url = self._abs_url_from_link(link)
            result += self._switch_on_crawled_type(path, link, abs_url)

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

        self._cookie_jar.save_cookies("Authed")

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


def run_as_test(ilias_url: str, course_id: int) -> List[IliasDownloadInfo]:
    from ..organizer import Organizer
    from .authenticators import KitShibbolethAuthenticator

    crawler = IliasCrawler(KitShibbolethAuthenticator(), ilias_url, str(course_id))
    return crawler.crawl()
