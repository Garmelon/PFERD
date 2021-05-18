import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import PurePath
# TODO In Python 3.9 and above, AsyncContextManager is deprecated
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlsplit, urlunsplit

import aiohttp
from bs4 import BeautifulSoup, Tag

from PFERD.output_dir import Redownload
from PFERD.utils import soupify

from ..authenticators import Authenticator
from ..conductor import TerminalConductor
from ..config import Config
from ..crawler import CrawlerSection, HttpCrawler, anoncritical, arepeat

TargetType = Union[str, int]


class KitIliasCrawlerSection(CrawlerSection):

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
        return self.s.getboolean("link_file_plain_text", fallback=False)


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
    description: Optional[str] = None


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
            description = self._find_link_description(link)

            if not element_type:
                continue
            if element_type == IliasElementType.MEETING:
                element_name = _sanitize_path_name(self._normalize_meeting_name(element_name))
            elif element_type == IliasElementType.FILE:
                result.append(self._file_to_element(element_name, abs_url, link))
                continue

            result.append(IliasPageElement(element_type, abs_url, element_name, description=description))

        return result

    def _find_link_description(self, link: Tag) -> Optional[str]:
        tile: Tag = link.findParent("div", {"class": lambda x: x and "il_ContainerListItem" in x})
        if not tile:
            return None
        description_element: Tag = tile.find("div", {"class": lambda x: x and "il_Description" in x})
        if not description_element:
            return None
        return description_element.getText().strip()

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


class KitIliasCrawler(HttpCrawler):
    def __init__(
            self,
            name: str,
            section: KitIliasCrawlerSection,
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
        self._link_file_redirect_delay = section.link_file_redirect_delay()
        self._link_file_use_plaintext = section.link_file_use_plaintext()

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

        if not self.should_crawl(element_path):
            return

        if element.type == IliasElementType.FILE:
            await self._download_file(element, element_path)
        elif element.type == IliasElementType.FORUM:
            # TODO: Delete
            self.print(f"Skipping forum [green]{element_path}[/]")
        elif element.type == IliasElementType.LINK:
            await self._download_link(element, element_path)
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
    async def _download_link(self, element: IliasPageElement, element_path: PurePath) -> None:
        dl = await self.download(element_path, mtime=element.mtime)
        if not dl:
            return

        async with self.download_bar(element_path):
            export_url = element.url.replace("cmd=calldirectlink", "cmd=exportHTML")
            async with self.session.get(export_url) as response:
                html_page: BeautifulSoup = soupify(await response.read())
                real_url: str = html_page.select_one("a").get("href").strip()

            async with dl as sink:
                content = _link_template_plain if self._link_file_use_plaintext else _link_template_rich
                content = content.replace("{{link}}", real_url)
                content = content.replace("{{name}}", element.name)
                content = content.replace("{{description}}", str(element.description))
                content = content.replace("{{redirect_delay}}", str(self._link_file_redirect_delay))
                sink.file.write(content.encode("utf-8"))
                sink.done()

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
        print(url, "retries left", retries_left)
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

_link_template_plain = "{{link}}"
# flake8: noqa E501
_link_template_rich = """
<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>ILIAS - Link: {{name}}</title>
        <meta http-equiv = "refresh" content = "{{redirect_delay}}; url = {{link}}" />
    </head>

    <style>
    * {
        box-sizing: border-box;
    }
    .center-flex {
        display: flex;
        align-items: center;
        justify-content: center;
    }
    body {
        padding: 0;
        margin: 0;
        background-color: #f0f0f0;
        font-family: "Open Sans", Verdana, Arial, Helvetica, sans-serif;
        height: 100vh;
    }
    .row {
        background-color: white;
        min-width: 500px;
        max-width: 90vw;
        display: flex;
        padding: 1em;
    }
    .logo {
        flex: 0 1;
        margin-right: 1em;
        fill: #009682;
    }
    .tile {
        flex: 1 0;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }
    .top-row {
        padding-bottom: 5px;
        font-size: 15px;
    }
    a {
        color: #009682;
        text-decoration: none;
    }
    a:hover {
        text-decoration: underline;
    }
    .bottom-row {
        font-size: 13px;
    }
    .menu-button {
        border: 1px solid black;
        margin-left: 4em;
        width: 25px;
        height: 25px;
        flex: 0 0 25px;
        background-color: #b3e0da;
        font-size: 13px;
        color: #222;
    }
    </style>
    <body class="center-flex">
        <div class="row">
            <div class="logo center-flex">
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
                    <path d="M12 0c-6.627 0-12 5.373-12 12s5.373 12 12 12 12-5.373 12-12-5.373-12-12-12zm9.567 9.098c-.059-.058-.127-.108-.206-.138-.258-.101-1.35.603-1.515.256-.108-.231-.327.148-.578.008-.121-.067-.459-.52-.611-.465-.312.112.479.974.694 1.087.203-.154.86-.469 1.002-.039.271.812-.745 1.702-1.264 2.171-.775.702-.63-.454-1.159-.86-.277-.213-.274-.667-.555-.824-.125-.071-.7-.732-.694-.821l-.017.167c-.095.072-.297-.27-.319-.325 0 .298.485.772.646 1.011.273.409.42 1.005.756 1.339.179.18.866.923 1.045.908l.921-.437c.649.154-1.531 3.237-1.738 3.619-.171.321.139 1.112.114 1.49-.029.437-.374.579-.7.817-.35.255-.268.752-.562.934-.521.321-.897 1.366-1.639 1.361-.219-.001-1.151.364-1.273.007-.095-.258-.223-.455-.356-.71-.131-.25-.015-.51-.175-.731-.11-.154-.479-.502-.513-.684-.002-.157.118-.632.283-.715.231-.118.044-.462.016-.663-.048-.357-.27-.652-.535-.859-.393-.302-.189-.542-.098-.974 0-.206-.126-.476-.402-.396-.57.166-.396-.445-.812-.417-.299.021-.543.211-.821.295-.349.104-.707-.083-1.053-.126-1.421-.179-1.885-1.804-1.514-2.976.037-.192-.115-.547-.048-.696.159-.352.485-.752.768-1.021.16-.152.365-.113.553-.231.29-.182.294-.558.578-.789.404-.328.956-.321 1.482-.392.281-.037 1.35-.268 1.518-.06 0 .039.193.611-.019.578.438.023 1.061.756 1.476.585.213-.089.135-.744.573-.427.265.19 1.45.275 1.696.07.152-.125.236-.939.053-1.031.117.116-.618.125-.686.099-.122-.044-.235.115-.43.025.117.055-.651-.358-.22-.674-.181.132-.349-.037-.544.109-.135.109.062.181-.13.277-.305.155-.535-.53-.649-.607-.118-.077-1.024-.713-.777-.298l.797.793c-.04.026-.209-.289-.209-.059.053-.136.02.585-.105.35-.056-.09.091-.14.006-.271 0-.085-.23-.169-.275-.228-.126-.157-.462-.502-.644-.585-.05-.024-.771.088-.832.111-.071.099-.131.203-.181.314-.149.055-.29.127-.423.216l-.159.356c-.068.061-.772.294-.776.303.03-.076-.492-.172-.457-.324.038-.167.215-.687.169-.877-.048-.199 1.085.287 1.158-.238.029-.227.047-.492-.316-.531.069.008.702-.249.807-.364.148-.169.486-.447.731-.447.286 0 .225-.417.356-.622.133.053-.071.38.088.512-.01-.104.45.057.494.033.105-.056.691-.023.601-.299-.101-.28.052-.197.183-.255-.02.008.248-.458.363-.456-.104-.089-.398.112-.516.103-.308-.024-.177-.525-.061-.672.09-.116-.246-.258-.25-.036-.006.332-.314.633-.243 1.075.109.666-.743-.161-.816-.115-.283.172-.515-.216-.368-.449.149-.238.51-.226.659-.48.104-.179.227-.389.388-.524.541-.454.689-.091 1.229-.042.526.048.178.125.105.327-.07.192.289.261.413.1.071-.092.232-.326.301-.499.07-.175.578-.2.527-.365 2.72 1.148 4.827 3.465 5.694 6.318zm-11.113-3.779l.068-.087.073-.019c.042-.034.086-.118.151-.104.043.009.146.095.111.148-.037.054-.066-.049-.081.101-.018.169-.188.167-.313.222-.087.037-.175-.018-.09-.104l.088-.108-.007-.049zm.442.245c.046-.045.138-.008.151-.094.014-.084.078-.178-.008-.335-.022-.042.116-.082.051-.137l-.109.032s.155-.668.364-.366l-.089.103c.135.134.172.47.215.687.127.066.324.078.098.192.117-.02-.618.314-.715.178-.072-.083.317-.139.307-.173-.004-.011-.317-.02-.265-.087zm1.43-3.547l-.356.326c-.36.298-1.28.883-1.793.705-.524-.18-1.647.667-1.826.673-.067.003.002-.641.36-.689-.141.021.993-.575 1.185-.805.678-.146 1.381-.227 2.104-.227l.326.017zm-5.086 1.19c.07.082.278.092-.026.288-.183.11-.377.809-.548.809-.51.223-.542-.439-1.109.413-.078.115-.395.158-.644.236.685-.688 1.468-1.279 2.327-1.746zm-5.24 8.793c0-.541.055-1.068.139-1.586l.292.185c.113.135.113.719.169.911.139.482.484.751.748 1.19.155.261.414.923.332 1.197.109-.179 1.081.824 1.259 1.033.418.492.74 1.088.061 1.574-.219.158.334 1.14.049 1.382l-.365.094c-.225.138-.235.397-.166.631-1.562-1.765-2.518-4.076-2.518-6.611zm14.347-5.823c.083-.01-.107.167-.107.167.033.256.222.396.581.527.437.157.038.455-.213.385-.139-.039-.854-.255-.879.025 0 .167-.679.001-.573-.175.073-.119.05-.387.186-.562.193-.255.38-.116.386.032-.001.394.398-.373.619-.399z"/>
                </svg>
            </div>
            <div class="tile">
                <div class="top-row">
                    <a href="{{link}}">{{name}}</a>
                </div>
                <div class="bottom-row">{{description}}</div>
            </div>
            <div class="menu-button center-flex"> ⯆ </div>
        </div>
    </body>
</html>
"""
