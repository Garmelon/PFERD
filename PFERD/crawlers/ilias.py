import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import PurePath
# TODO In Python 3.9 and above, AsyncContextManager is deprecated
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import (parse_qs, urlencode, urljoin, urlparse, urlsplit,
                          urlunsplit)

import aiohttp
from bs4 import BeautifulSoup, Tag
from PFERD.output_dir import Redownload
from PFERD.utils import soupify

from ..authenticators import Authenticator
from ..conductor import TerminalConductor
from ..config import Config
from ..crawler import CrawlerSection, HttpCrawler, anoncritical, arepeat

TargetType = Union[str, int]


class IliasCrawlerSection(CrawlerSection):

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


class IliasElementType(Enum):
    EXERCISE = "exercise"
    FILE = "file"
    FOLDER = "folder"
    FORUM = "forum"
    LINK = "link"
    MEETING = "meeting"
    VIDEO = "video"
    VIDEO_PLAYER = "video_player"
    VIDEO_FOLDER = "video_folder"
    VIDEO_FOLDER_MAYBE_PAGINATED = "video_folder_maybe_paginated"


@dataclass
class IliasPageElement:
    type: IliasElementType
    url: str
    name: str
    mtime: Optional[datetime] = None


class IliasPage:

    def __init__(self, soup: BeautifulSoup, _page_url: str, source_element: Optional[IliasPageElement]):
        self._soup = soup
        self._page_url = _page_url
        self._page_type = source_element.type if source_element else None
        self._source_name = source_element.name if source_element else ""

    def get_child_elements(self) -> List[IliasPageElement]:
        """
        Return all child page elements you can find here.
        """
        if self._is_video_player():
            return self._player_to_video()
        if self._is_video_listing():
            return self._find_video_entries()
        if self._is_exercise_file():
            return self._find_exercise_entries()
        return self._find_normal_entries()

    def _is_video_player(self) -> bool:
        return "paella_config_file" in str(self._soup)

    def _is_video_listing(self) -> bool:
        # ILIAS fluff around it
        if self._soup.find(id="headerimage"):
            element: Tag = self._soup.find(id="headerimage")
            if "opencast" in element.attrs["src"].lower():
                return True

        # Raw listing without ILIAS fluff
        video_element_table: Tag = self._soup.find(
            name="table", id=re.compile(r"tbl_xoct_.+")
        )
        return video_element_table is not None

    def _is_exercise_file(self) -> bool:
        # we know it from before
        if self._page_type == IliasElementType.EXERCISE:
            return True

        # We have no suitable parent - let's guesss
        if self._soup.find(id="headerimage"):
            element: Tag = self._soup.find(id="headerimage")
            if "exc" in element.attrs["src"].lower():
                return True

        return False

    def _player_to_video(self) -> List[IliasPageElement]:
        # Fetch the actual video page. This is a small wrapper page initializing a javscript
        # player. Sadly we can not execute that JS. The actual video stream url is nowhere
        # on the page, but defined in a JS object inside a script tag, passed to the player
        # library.
        # We do the impossible and RegEx the stream JSON object out of the page's HTML source
        regex: re.Pattern[str] = re.compile(
            r"({\"streams\"[\s\S]+?),\s*{\"paella_config_file", re.IGNORECASE
        )
        json_match = regex.search(str(self._soup))

        if json_match is None:
            print(f"Could not find json stream info for {self._page_url!r}")
            return []
        json_str = json_match.group(1)

        # parse it
        json_object = json.loads(json_str)
        # and fetch the video url!
        video_url = json_object["streams"][0]["sources"]["mp4"][0]["src"]
        return [IliasPageElement(IliasElementType.VIDEO, video_url, self._source_name)]

    def _find_video_entries(self) -> List[IliasPageElement]:
        # ILIAS has three stages for video pages
        # 1. The initial dummy page without any videos. This page contains the link to the listing
        # 2. The video listing which might be paginated
        # 3. An unpaginated video listing (or at least one that includes 800 videos)
        #
        # We need to figure out where we are.

        video_element_table: Tag = self._soup.find(
            name="table", id=re.compile(r"tbl_xoct_.+")
        )

        if video_element_table is None:
            # We are in stage 1
            # The page is actually emtpy but contains the link to stage 2
            content_link: Tag = self._soup.select_one("#tab_series a")
            url: str = self._abs_url_from_link(content_link)
            query_params = {"limit": "800", "cmd": "asyncGetTableGUI", "cmdMode": "asynch"}
            url = _url_set_query_params(url, query_params)
            return [IliasPageElement(IliasElementType.VIDEO_FOLDER_MAYBE_PAGINATED, url, "")]

        is_paginated = self._soup.find(id=re.compile(r"tab_page_sel.+")) is not None

        if is_paginated and not self._page_type == IliasElementType.VIDEO_FOLDER:
            # We are in stage 2 - try to break pagination
            return self._find_video_entries_paginated()

        return self._find_video_entries_no_paging()

    def _find_video_entries_paginated(self) -> List[IliasPageElement]:
        table_element: Tag = self._soup.find(name="table", id=re.compile(r"tbl_xoct_.+"))

        if table_element is None:
            # TODO: Properly log this
            print(
                "Could not increase elements per page (table not found)."
                " Some might not be crawled!"
            )
            return self._find_video_entries_no_paging()

        id_match = re.match(r"tbl_xoct_(.+)", table_element.attrs["id"])
        if id_match is None:
            # TODO: Properly log this
            print(
                "Could not increase elements per page (table id not found)."
                " Some might not be crawled!"
            )
            return self._find_video_entries_no_paging()

        table_id = id_match.group(1)

        query_params = {f"tbl_xoct_{table_id}_trows": "800",
                        "cmd": "asyncGetTableGUI", "cmdMode": "asynch"}
        url = _url_set_query_params(self._page_url, query_params)
        return [IliasPageElement(IliasElementType.VIDEO_FOLDER, url, "")]

    def _find_video_entries_no_paging(self) -> List[IliasPageElement]:
        """
        Crawls the "second stage" video page. This page contains the actual video urls.
        """
        # Video start links are marked with an "Abspielen" link
        video_links: List[Tag] = self._soup.findAll(
            name="a", text=re.compile(r"\s*Abspielen\s*")
        )

        results: List[IliasPageElement] = []

        # TODO: Sadly the download button is currently broken, so never do that
        for link in video_links:
            results.append(self._listed_video_to_element(link))

        return results

    def _listed_video_to_element(self, link: Tag) -> IliasPageElement:
        # The link is part of a table with multiple columns, describing metadata.
        # 6th child (1 indexed) is the modification time string
        modification_string = link.parent.parent.parent.select_one(
            "td.std:nth-child(6)"
        ).getText().strip()
        modification_time = datetime.strptime(modification_string, "%d.%m.%Y - %H:%M")

        title = link.parent.parent.parent.select_one("td.std:nth-child(3)").getText().strip()
        title += ".mp4"

        video_name: str = _sanitize_path_name(title)

        video_url = self._abs_url_from_link(link)

        return IliasPageElement(IliasElementType.VIDEO_PLAYER, video_url, video_name, modification_time)

    def _find_exercise_entries(self) -> List[IliasPageElement]:
        results: List[IliasPageElement] = []

        # Each assignment is in an accordion container
        assignment_containers: List[Tag] = self._soup.select(".il_VAccordionInnerContainer")

        for container in assignment_containers:
            # Fetch the container name out of the header to use it in the path
            container_name = container.select_one(".ilAssignmentHeader").getText().strip()
            # Find all download links in the container (this will contain all the files)
            files: List[Tag] = container.findAll(
                name="a",
                # download links contain the given command class
                attrs={"href": lambda x: x and "cmdClass=ilexsubmissiongui" in x},
                text="Download"
            )

            # Grab each file as you now have the link
            for file_link in files:
                # Two divs, side by side. Left is the name, right is the link ==> get left
                # sibling
                file_name = file_link.parent.findPrevious(name="div").getText().strip()
                file_name = _sanitize_path_name(file_name)
                url = self._abs_url_from_link(file_link)

                results.append(IliasPageElement(
                    IliasElementType.FILE,
                    url,
                    container_name + "/" + file_name,
                    None  # We do not have any timestamp
                ))

        return results

    def _find_normal_entries(self) -> List[IliasPageElement]:
        result: List[IliasPageElement] = []

        # Fetch all links and throw them to the general interpreter
        links: List[Tag] = self._soup.select("a.il_ContainerItemTitle")

        for link in links:
            abs_url = self._abs_url_from_link(link)
            element_name = _sanitize_path_name(link.getText())
            element_type = self._find_type_from_link(element_name, link, abs_url)

            if not element_type:
                continue
            if element_type == IliasElementType.MEETING:
                element_name = _sanitize_path_name(self._normalize_meeting_name(element_name))
            elif element_type == IliasElementType.FILE:
                result.append(self._file_to_element(element_name, abs_url, link))
                continue

            result.append(IliasPageElement(element_type, abs_url, element_name, None))

        return result

    def _file_to_element(self, name: str, url: str, link_element: Tag) -> IliasPageElement:
        # Files have a list of properties (type, modification date, size, etc.)
        # In a series of divs.
        # Find the parent containing all those divs, so we can filter our what we need
        properties_parent: Tag = link_element.findParent(
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
            # TODO: Properly log this
            print(f"Could not extract start date from {all_properties_text!r}")
        else:
            modification_date_str = modification_date_match.group(1)
            modification_date = demangle_date(modification_date_str)

        # Grab the name from the link text
        name = _sanitize_path_name(link_element.getText())
        full_path = name + "." + file_type

        return IliasPageElement(IliasElementType.FILE, url, full_path, modification_date)

    @staticmethod
    def _find_type_from_link(
            element_name: str,
            link_element: Tag,
            url: str
    ) -> Optional[IliasElementType]:
        """
        Decides which sub crawler to use for a given top level element.
        """
        parsed_url = urlparse(url)

        # file URLs contain "target=file"
        if "target=file_" in parsed_url.query:
            return IliasElementType.FILE

        # Skip forums
        if "cmd=showThreads" in parsed_url.query:
            return IliasElementType.FORUM

        # Everything with a ref_id can *probably* be opened to reveal nested things
        # video groups, directories, exercises, etc
        if "ref_id=" in parsed_url.query:
            return IliasPage._find_type_from_folder_like(link_element, url)

        # TODO: Log this properly
        print(f"Unknown type: The element was at {str(element_name)!r} and it is {link_element!r})")
        return None

    @staticmethod
    def _find_type_from_folder_like(link_element: Tag, url: str) -> Optional[IliasElementType]:
        """
        Try crawling something that looks like a folder.
        """
        # pylint: disable=too-many-return-statements

        found_parent: Optional[Tag] = None

        # We look for the outer div of our inner link, to find information around it
        # (mostly the icon)
        for parent in link_element.parents:
            if "ilContainerListItemOuter" in parent["class"]:
                found_parent = parent
                break

        if found_parent is None:
            # TODO: Log this properly
            print(f"Could not find element icon for {url!r}")
            return None

        # Find the small descriptive icon to figure out the type
        img_tag: Optional[Tag] = found_parent.select_one("img.ilListItemIcon")

        if img_tag is None:
            # TODO: Log this properly
            print(f"Could not find image tag for {url!r}")
            return None

        if "opencast" in str(img_tag["alt"]).lower():
            return IliasElementType.VIDEO_FOLDER

        if str(img_tag["src"]).endswith("icon_exc.svg"):
            return IliasElementType.EXERCISE

        if str(img_tag["src"]).endswith("icon_webr.svg"):
            return IliasElementType.LINK

        if str(img_tag["src"]).endswith("frm.svg"):
            return IliasElementType.FORUM

        if str(img_tag["src"]).endswith("sess.svg"):
            return IliasElementType.MEETING

        return IliasElementType.FOLDER

    @staticmethod
    def _normalize_meeting_name(meeting_name: str) -> str:
        """
        Normalizes meeting names, which have a relative time as their first part,
        to their date in ISO format.
        """
        date_portion_str = meeting_name.split(" - ")[0]
        date_portion = demangle_date(date_portion_str)

        if not date_portion:
            return meeting_name

        rest_of_name = meeting_name
        if rest_of_name.startswith(date_portion_str):
            rest_of_name = rest_of_name[len(date_portion_str):]

        return datetime.strftime(date_portion, "%Y-%m-%d, %H:%M") + rest_of_name

    def _abs_url_from_link(self, link_tag: Tag) -> str:
        """
        Create an absolute url from an <a> tag.
        """
        return urljoin(self._page_url, link_tag.get("href"))


german_months = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
english_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def demangle_date(date_str: str) -> Optional[datetime]:
    """
    Demangle a given date in one of the following formats:
    "Gestern, HH:MM"
    "Heute, HH:MM"
    "Morgen, HH:MM"
    "dd. mon yyyy, HH:MM
    """
    try:
        date_str = re.sub(r"\s+", " ", date_str)
        date_str = re.sub("Gestern|Yesterday", _format_date_english(_yesterday()), date_str, re.I)
        date_str = re.sub("Heute|Today", _format_date_english(date.today()), date_str, re.I)
        date_str = re.sub("Morgen|Tomorrow",  _format_date_english(_tomorrow()), date_str, re.I)
        for german, english in zip(german_months, english_months):
            date_str = date_str.replace(german, english)
            # Remove trailing dots for abbreviations, e.g. "20. Apr. 2020" -> "20. Apr 2020"
            date_str = date_str.replace(english + ".", english)

        # We now have a nice english String in the format: "dd. mmm yyyy, hh:mm"
        day_part, time_part = date_str.split(",")
        day_str, month_str, year_str = day_part.split(" ")

        day = int(day_str.strip().replace(".", ""))
        month = english_months.index(month_str.strip()) + 1
        year = int(year_str.strip())

        hour_str, minute_str = time_part.split(":")
        hour = int(hour_str)
        minute = int(minute_str)

        return datetime(year, month, day, hour, minute)
    except Exception:
        # TODO: Properly log this
        print(f"Could not parse date {date_str!r}")
        return None


def _format_date_english(date_to_format: date) -> str:
    month = english_months[date_to_format.month - 1]
    return f"{date_to_format.day:02d}. {month} {date_to_format.year:04d}"


def _yesterday() -> date:
    return date.today() - timedelta(days=1)


def _tomorrow() -> date:
    return date.today() + timedelta(days=1)


def _sanitize_path_name(name: str) -> str:
    return name.replace("/", "-").replace("\\", "-").strip()


def _url_set_query_param(url: str, param: str, value: str) -> str:
    """
    Set a query parameter in an url, overwriting existing ones with the same name.
    """
    scheme, netloc, path, query, fragment = urlsplit(url)
    query_parameters = parse_qs(query)
    query_parameters[param] = [value]
    new_query_string = urlencode(query_parameters, doseq=True)

    return urlunsplit((scheme, netloc, path, new_query_string, fragment))


def _url_set_query_params(url: str, params: Dict[str, str]) -> str:
    result = url

    for key, val in params.items():
        result = _url_set_query_param(result, key, val)

    return result


_DIRECTORY_PAGES: Set[IliasElementType] = set([
    IliasElementType.EXERCISE,
    IliasElementType.FOLDER,
    IliasElementType.MEETING,
    IliasElementType.VIDEO_FOLDER,
    IliasElementType.VIDEO_FOLDER_MAYBE_PAGINATED,
])


class IliasCrawler(HttpCrawler):
    def __init__(
            self,
            name: str,
            section: IliasCrawlerSection,
            config: Config,
            conductor: TerminalConductor,
            authenticators: Dict[str, Authenticator]
    ):
        super().__init__(name, section, config, conductor)

        self._shibboleth_login = KitShibbolethLogin(
            section.auth(authenticators),
            section.tfa_auth(authenticators)
        )
        self._base_url = "https://ilias.studium.kit.edu"

        self._target = section.target()

    async def crawl(self) -> None:
        if isinstance(self._target, int):
            await self._crawl_course(self._target)
        elif self._target == "desktop":
            await self._crawl_desktop()
        else:
            await self._crawl_url(self._target)

        if self.error_free:
            await self.cleanup()

    async def _crawl_course(self, course_id: int) -> None:
        # Start crawling at the given course
        root_url = _url_set_query_param(
            self._base_url + "/goto.php", "target", f"crs_{course_id}"
        )

        await self._crawl_url(root_url, expected_id=course_id)

    async def _crawl_desktop(self) -> None:
        await self._crawl_url(self._base_url)

    @arepeat(3)
    async def _crawl_url(self, url: str, expected_id: Optional[int] = None) -> None:
        tasks = []

        async with self.crawl_bar(PurePath("Root element")):
            soup = await self._get_page(url)

            if expected_id is not None:
                perma_link_element: Tag = soup.find(id="current_perma_link")
                if not perma_link_element or "crs_" not in perma_link_element.get("value"):
                    # TODO: Properly handle error
                    raise RuntimeError(
                        "Invalid course id? I didn't find anything looking like a course!")

            # Duplicated code, but the root page is special - we want to void fetching it twice!
            page = IliasPage(soup, url, None)
            for child in page.get_child_elements():
                tasks.append(self._handle_ilias_element(PurePath("."), child))

        await asyncio.gather(*tasks)

    @arepeat(3)
    @anoncritical
    async def _handle_ilias_page(self, url: str, parent: IliasPageElement, path: PurePath) -> None:
        tasks = []
        async with self.crawl_bar(path):
            soup = await self._get_page(url)
            page = IliasPage(soup, url, parent)

            for child in page.get_child_elements():
                tasks.append(self._handle_ilias_element(path, child))

        await asyncio.gather(*tasks)

    @anoncritical
    async def _handle_ilias_element(self, parent_path: PurePath, element: IliasPageElement) -> None:
        element_path = PurePath(parent_path, element.name)

        if element.type == IliasElementType.FILE:
            await self._download_file(element, element_path)
        elif element.type == IliasElementType.FORUM:
            # TODO: Delete
            self.print(f"Skipping forum [green]{element_path}[/]")
        elif element.type == IliasElementType.LINK:
            # TODO: Write in meta-redirect file
            self.print(f"Skipping link [green]{element_path}[/]")
        elif element.type == IliasElementType.VIDEO:
            await self._download_file(element, element_path)
        elif element.type == IliasElementType.VIDEO_PLAYER:
            await self._download_video(element, element_path)
        elif element.type in _DIRECTORY_PAGES:
            await self._handle_ilias_page(element.url, element, element_path)
        else:
            # TODO: Proper exception
            raise RuntimeError(f"Unknown type: {element.type!r}")

    @arepeat(3)
    async def _download_video(self, element: IliasPageElement, element_path: PurePath) -> None:
        # Videos will NOT be redownloaded - their content doesn't really change and they are chunky
        dl = await self.download(element_path, mtime=element.mtime, redownload=Redownload.NEVER)
        if not dl:
            return

        async with self.download_bar(element_path) as bar:
            page = IliasPage(await self._get_page(element.url), element.url, element)
            real_element = page.get_child_elements()[0]

            async with dl as sink, self.session.get(real_element.url) as resp:
                if resp.content_length:
                    bar.set_total(resp.content_length)

                async for data in resp.content.iter_chunked(1024):
                    sink.file.write(data)
                    bar.advance(len(data))

                sink.done()

    @arepeat(3)
    async def _download_file(self, element: IliasPageElement, element_path: PurePath) -> None:
        dl = await self.download(element_path, mtime=element.mtime)
        if not dl:
            return

        async with self.download_bar(element_path) as bar:
            async with dl as sink, self.session.get(element.url) as resp:
                if resp.content_length:
                    bar.set_total(resp.content_length)

                async for data in resp.content.iter_chunked(1024):
                    sink.file.write(data)
                    bar.advance(len(data))

                sink.done()

    async def _get_page(self, url: str, retries_left: int = 3) -> BeautifulSoup:
        # This function will retry itself a few times if it is not logged in - it won't handle
        # connection errors
        if retries_left < 0:
            # TODO: Proper exception
            raise RuntimeError("Get page failed too often")
        print(url)
        async with self.session.get(url) as request:
            soup = soupify(await request.read())
            if self._is_logged_in(soup):
                return soup

        await self._shibboleth_login.login(self.session)

        return await self._get_page(url, retries_left - 1)

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
