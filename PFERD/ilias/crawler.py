"""
Contains an ILIAS crawler alongside helper functions.
"""

import datetime
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import (parse_qs, urlencode, urljoin, urlparse, urlsplit,
                          urlunsplit)

import bs4
import requests

from ..cookie_jar import CookieJar
from ..utils import soupify
from .authenticators import IliasAuthenticator
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
        scheme, netloc, path, query, fragment = urlsplit(url)
        query_parameters = parse_qs(query)
        query_parameters[param] = [value]
        new_query_string = urlencode(query_parameters, doseq=True)

        return urlunsplit((scheme, netloc, path, new_query_string, fragment))

    def crawl(self) -> List[IliasDownloadInfo]:
        """
        Starts the crawl process, yielding a list of elements to (potentially) download.
        """
        root_url = self._url_set_query_param(
            self._base_url + "/goto.php", "target", f"crs_{self._course_id}"
        )

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
        LOGGER.debug("Parsed url: %s", repr(parsed_url))

        if "target=file_" in parsed_url.query:
            return self._crawl_file(path, link_element, url)

        # Skip forums
        if "cmd=showThreads" in parsed_url.query:
            LOGGER.debug("Skipping forum %s", repr(url))
            return []

        if "ref_id=" in parsed_url.query:
            LOGGER.debug("Processing folder-like...")
            return self._switch_on_folder_like(path, link_element, url)

        LOGGER.warning("Got unknown type, %s, %s, %s", repr(path), repr(link_element), repr(url))
        # TODO: Other types
        raise Exception("Implement me!")

    @staticmethod
    def _crawl_file(path: Path, link_element: bs4.Tag, url: str) -> List[IliasDownloadInfo]:
        """
        Crawls a file.
        """
        properties_parent: bs4.Tag = link_element.findParent(
            "div", {"class": lambda x: "il_ContainerListItem" in x}
        ).select_one(".il_ItemProperties")
        file_type = properties_parent.select_one("span.il_ItemProperty").getText().strip()

        modifcation_date = datetime.datetime.now()
        all_properties_text = properties_parent.getText().strip()
        print("Property text is", all_properties_text)
        # todo demangle date from text above

        name = link_element.getText()
        full_path = Path(path, name + "." + file_type)

        match_result = re.match(r".+target=file_(\d+).+", url)

        if match_result is None:
            LOGGER.warning("Could not download file %s", repr(url))
            return []

        return [IliasDownloadInfo(full_path, url, modifcation_date)]

    def _switch_on_folder_like(
            self,
            path: Path,
            link_element: bs4.Tag,
            url: str
    ) -> List[IliasDownloadInfo]:
        found_parent: Optional[bs4.Tag] = None

        for parent in link_element.parents:
            if "ilContainerListItemOuter" in parent["class"]:
                found_parent = parent
                break

        if found_parent is None:
            LOGGER.warning("Could not find element icon for %s", repr(url))
            return []

        img_tag: Optional[bs4.Tag] = found_parent.select_one("img.ilListItemIcon")

        if img_tag is None:
            LOGGER.warning("Could not find image tag for %s", repr(url))
            return []

        if str(img_tag["src"]).endswith("frm.svg"):
            LOGGER.debug("Skipping forum at %s", repr(url))
            return []

        # Assume it is a folder
        folder_name = link_element.getText()
        folder_path = Path(path, folder_name)
        return self._crawl_folder(folder_path, self._abs_url_from_link(link_element))

    def _crawl_folder(self, path: Path, url: str) -> List[IliasDownloadInfo]:
        soup = self._get_page(url, {})

        result: List[IliasDownloadInfo] = []

        links: List[bs4.Tag] = soup.select("a.il_ContainerItemTitle")
        for link in links:
            abs_url = self._abs_url_from_link(link)
            result += self._switch_on_crawled_type(path, link, abs_url)

        return result

    def _get_page(self, url: str, params: Dict[str, Any]) -> bs4.BeautifulSoup:
        """
        Fetches a page from ILIAS, authenticating when needed.
        """
        print("Fetching", url)

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
        userlog = soup.find("li", {"id": "userlog"})
        return userlog is not None


def run_as_test(ilias_url: str, course_id: int) -> List[IliasDownloadInfo]:
    from ..organizer import Organizer
    from .authenticators import KitShibbolethAuthenticator
    organizer = Organizer(Path("/tmp/test/inner"))

    crawler = IliasCrawler(KitShibbolethAuthenticator(), ilias_url, str(course_id))
    return crawler.crawl()
