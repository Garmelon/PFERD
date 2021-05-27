import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import List, Optional, Union
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from PFERD.logging import log
from PFERD.utils import url_set_query_params

TargetType = Union[str, int]


class IliasElementType(Enum):
    EXERCISE = "exercise"
    EXERCISE_FILES = "exercise_files"  # own submitted files
    TEST = "test"                      # an online test. Will be ignored currently.
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
            log.explain("Page is a video player, extracting URL")
            return self._player_to_video()
        if self._is_video_listing():
            log.explain("Page is a video listing, searching for elements")
            return self._find_video_entries()
        if self._is_exercise_file():
            log.explain("Page is an exercise, searching for elements")
            return self._find_exercise_entries()
        log.explain("Page is a normal folder, searching for elements")
        return self._find_normal_entries()

    def get_next_stage_url(self) -> Optional[str]:
        if self._is_ilias_opencast_embedding():
            return self.get_child_elements()[0].url
        return None

    def _is_video_player(self) -> bool:
        return "paella_config_file" in str(self._soup)

    def _is_video_listing(self) -> bool:
        if self._is_ilias_opencast_embedding():
            return True

        # Raw listing without ILIAS fluff
        video_element_table: Tag = self._soup.find(
            name="table", id=re.compile(r"tbl_xoct_.+")
        )
        return video_element_table is not None

    def _is_ilias_opencast_embedding(self) -> bool:
        # ILIAS fluff around the real opencast html
        if self._soup.find(id="headerimage"):
            element: Tag = self._soup.find(id="headerimage")
            if "opencast" in element.attrs["src"].lower():
                return True
        return False

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
            log.warn("Could not find JSON stream info in video player. Ignoring video.")
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
            url = url_set_query_params(url, query_params)
            log.explain("Found ILIAS video frame page, fetching actual content next")
            return [IliasPageElement(IliasElementType.VIDEO_FOLDER_MAYBE_PAGINATED, url, "")]

        is_paginated = self._soup.find(id=re.compile(r"tab_page_sel.+")) is not None

        if is_paginated and not self._page_type == IliasElementType.VIDEO_FOLDER:
            # We are in stage 2 - try to break pagination
            return self._find_video_entries_paginated()

        return self._find_video_entries_no_paging()

    def _find_video_entries_paginated(self) -> List[IliasPageElement]:
        table_element: Tag = self._soup.find(name="table", id=re.compile(r"tbl_xoct_.+"))

        if table_element is None:
            log.warn("Couldn't increase elements per page (table not found). I might miss elements.")
            return self._find_video_entries_no_paging()

        id_match = re.match(r"tbl_xoct_(.+)", table_element.attrs["id"])
        if id_match is None:
            log.warn("Couldn't increase elements per page (table id not found). I might miss elements.")
            return self._find_video_entries_no_paging()

        table_id = id_match.group(1)

        query_params = {f"tbl_xoct_{table_id}_trows": "800",
                        "cmd": "asyncGetTableGUI", "cmdMode": "asynch"}
        url = url_set_query_params(self._page_url, query_params)

        log.explain("Disabled pagination, retrying folder as a new entry")
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

        log.explain(f"Found video {video_name!r} at {video_url}")
        return IliasPageElement(IliasElementType.VIDEO_PLAYER, video_url, video_name, modification_time)

    def _find_exercise_entries(self) -> List[IliasPageElement]:
        if self._soup.find(id="tab_submission"):
            log.explain("Found submission tab. This is an exercise detail page")
            return self._find_exercise_entries_detail_page()
        log.explain("Found no submission tab. This is an exercise root page")
        return self._find_exercise_entries_root_page()

    def _find_exercise_entries_detail_page(self) -> List[IliasPageElement]:
        results: List[IliasPageElement] = []

        # Find all download links in the container (this will contain all the files)
        download_links: List[Tag] = self._soup.findAll(
            name="a",
            # download links contain the given command class
            attrs={"href": lambda x: x and "cmd=download" in x},
            text="Download"
        )

        for link in download_links:
            parent_row: Tag = link.findParent("tr")
            children: List[Tag] = parent_row.findChildren("td")

            # <checkbox> <name> <uploader> <date> <download>
            #     0         1        2       3        4
            name = _sanitize_path_name(children[1].getText().strip())
            date = demangle_date(children[3].getText().strip())

            log.explain(f"Found exercise detail entry {name!r}")
            results.append(IliasPageElement(
                IliasElementType.FILE,
                self._abs_url_from_link(link),
                name,
                date
            ))

        return results

    def _find_exercise_entries_root_page(self) -> List[IliasPageElement]:
        results: List[IliasPageElement] = []

        # Each assignment is in an accordion container
        assignment_containers: List[Tag] = self._soup.select(".il_VAccordionInnerContainer")

        for container in assignment_containers:
            # Fetch the container name out of the header to use it in the path
            container_name = container.select_one(".ilAssignmentHeader").getText().strip()
            log.explain(f"Found exercise container {container_name!r}")

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

                log.explain(f"Found exercise entry {file_name!r}")
                results.append(IliasPageElement(
                    IliasElementType.FILE,
                    url,
                    container_name + "/" + file_name,
                    None  # We do not have any timestamp
                ))

            # Find all links to file listings (e.g. "Submitted Files" for groups)
            file_listings: List[Tag] = container.findAll(
                name="a",
                # download links contain the given command class
                attrs={"href": lambda x: x and "cmdClass=ilexsubmissionfilegui" in x}
            )

            # Add each listing as a new
            for listing in file_listings:
                file_name = _sanitize_path_name(listing.getText().strip())
                url = self._abs_url_from_link(listing)
                log.explain(f"Found exercise detail {file_name!r} at {url}")
                results.append(IliasPageElement(
                    IliasElementType.EXERCISE_FILES,
                    url,
                    container_name + "/" + file_name,
                    None  # we do not have any timestamp
                ))

        return results

    def _find_normal_entries(self) -> List[IliasPageElement]:
        result: List[IliasPageElement] = []

        # Fetch all links and throw them to the general interpreter
        links: List[Tag] = self._soup.select("a.il_ContainerItemTitle")

        for link in links:
            abs_url = self._abs_url_from_link(link)
            parents = self._find_upwards_folder_hierarchy(link)

            if parents:
                element_name = "/".join(parents) + "/" + _sanitize_path_name(link.getText())
            else:
                element_name = _sanitize_path_name(link.getText())

            element_type = self._find_type_from_link(element_name, link, abs_url)
            description = self._find_link_description(link)

            if not element_type:
                continue
            if element_type == IliasElementType.MEETING:
                normalized = _sanitize_path_name(self._normalize_meeting_name(element_name))
                log.explain(f"Normalized meeting name from {element_name!r} to {normalized!r}")
                element_name = normalized
            elif element_type == IliasElementType.FILE:
                result.append(self._file_to_element(element_name, abs_url, link))
                continue

            log.explain(f"Found {element_name!r}")
            result.append(IliasPageElement(element_type, abs_url, element_name, description=description))

        return result

    def _find_upwards_folder_hierarchy(self, tag: Tag) -> List[str]:
        """
        Interprets accordions and expandable blocks as virtual folders and returns them
        in order. This allows us to find a file named "Test" in an accordion "Acc" as "Acc/Test"
        """
        found_titles = []

        outer_accordion_content: Optional[Tag] = None

        parents: List[Tag] = list(tag.parents)
        for parent in parents:
            if not parent.get("class"):
                continue

            # ILIAS has proper accordions and weird blocks that look like normal headings,
            # but some JS later transforms them into an accordion.

            # This is for these weird JS-y blocks
            if "ilContainerItemsContainer" in parent.get("class"):
                # I am currently under the impression that *only* those JS blocks have an
                # ilNoDisplay class.
                if "ilNoDisplay" not in parent.get("class"):
                    continue
                prev: Tag = parent.findPreviousSibling("div")
                if "ilContainerBlockHeader" in prev.get("class"):
                    found_titles.append(prev.find("h3").getText().strip())

            # And this for real accordions
            if "il_VAccordionContentDef" in parent.get("class"):
                outer_accordion_content = parent
                break

        if outer_accordion_content:
            accordion_tag: Tag = outer_accordion_content.parent
            head_tag: Tag = accordion_tag.find(attrs={
                "class": lambda x: x and "ilc_va_ihead_VAccordIHead" in x
            })
            found_titles.append(head_tag.getText().strip())

        return [_sanitize_path_name(x) for x in reversed(found_titles)]

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
            log.explain(f"Element {name} at {url} has no date.")
        else:
            modification_date_str = modification_date_match.group(1)
            modification_date = demangle_date(modification_date_str)

        # Grab the name from the link text
        full_path = name + "." + file_type

        log.explain(f"Found file {full_path!r}")
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

        # Everything with a ref_id can *probably* be opened to reveal nested things
        # video groups, directories, exercises, etc
        if "ref_id=" in parsed_url.query:
            return IliasPage._find_type_from_folder_like(link_element, url)

        _unexpected_html_warning()
        log.warn_contd(
            f"Tried to figure out element type, but failed for {element_name!r} / {link_element!r})"
        )
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
            _unexpected_html_warning()
            log.warn_contd(f"Tried to figure out element type, but did not find an icon for {url}")
            return None

        # Find the small descriptive icon to figure out the type
        img_tag: Optional[Tag] = found_parent.select_one("img.ilListItemIcon")

        if img_tag is None:
            _unexpected_html_warning()
            log.warn_contd(f"Tried to figure out element type, but did not find an image for {url}")
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

        if str(img_tag["src"]).endswith("icon_tst.svg"):
            return IliasElementType.TEST

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


def _unexpected_html_warning() -> None:
    log.warn("Encountered unexpected HTML structure, ignoring element.")


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
        log.warn(f"Date parsing failed for {date_str!r}")
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
