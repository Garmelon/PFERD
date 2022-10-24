import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Union
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
    BOOKING = "booking"
    MEETING = "meeting"
    SURVEY = "survey"
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

    def id(self) -> str:
        regexes = [
            r"eid=(?P<id>[0-9a-z\-]+)",
            r"file_(?P<id>\d+)",
            r"ref_id=(?P<id>\d+)",
            r"target=[a-z]+_(?P<id>\d+)"
        ]

        for regex in regexes:
            if match := re.search(regex, self.url):
                return match.groupdict()["id"]

        # Fall back to URL
        log.warn(f"Didn't find identity for {self.name} - {self.url}. Please report this.")
        return self.url


@dataclass
class IliasDownloadForumData:
    url: str
    form_data: Dict[str, Union[str, List[str]]]
    empty: bool


@dataclass
class IliasForumThread:
    title: str
    title_tag: Tag
    content_tag: Tag
    mtime: Optional[datetime]


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
        if self._is_personal_desktop():
            log.explain("Page is the personal desktop, searching for elements")
            return self._find_personal_desktop_entries()
        if self._is_content_page():
            log.explain("Page is a content page, searching for elements")
            return self._find_copa_entries()
        log.explain("Page is a normal folder, searching for elements")
        return self._find_normal_entries()

    def get_description(self) -> Optional[BeautifulSoup]:
        def is_interesting_class(name: str) -> bool:
            return name in ["ilCOPageSection", "ilc_Paragraph", "ilc_va_ihcap_VAccordIHeadCap"]

        paragraphs: List[Tag] = self._soup.findAll(class_=is_interesting_class)
        if not paragraphs:
            return None

        # Extract bits and pieces into a string and parse it again.
        # This ensures we don't miss anything and weird structures are resolved
        # somewhat gracefully.
        raw_html = ""
        for p in paragraphs:
            if p.find_parent(class_=is_interesting_class):
                continue

            # Ignore special listings (like folder groupings)
            if "ilc_section_Special" in p["class"]:
                continue

            raw_html += str(p) + "\n"
        raw_html = f"<body>\n{raw_html}\n</body>"

        return BeautifulSoup(raw_html, "html.parser")

    def get_download_forum_data(self) -> Optional[IliasDownloadForumData]:
        form = self._soup.find("form", attrs={"action": lambda x: x and "fallbackCmd=showThreads" in x})
        if not form:
            return None
        post_url = self._abs_url_from_relative(form["action"])

        thread_ids = [f["value"] for f in form.find_all(attrs={"name": "thread_ids[]"})]

        form_data: Dict[str, Union[str, List[ſtr]]] = {
            "thread_ids[]": thread_ids,
            "selected_cmd2": "html",
            "select_cmd2": "Ausführen",
            "selected_cmd": "",
        }

        return IliasDownloadForumData(url=post_url, form_data=form_data, empty=len(thread_ids) == 0)

    def get_next_stage_element(self) -> Optional[IliasPageElement]:
        if self._is_forum_page():
            if "trows=800" in self._page_url:
                return None
            log.explain("Requesting *all* forum threads")
            return self._get_show_max_forum_entries_per_page_url()
        if self._is_ilias_opencast_embedding():
            log.explain("Unwrapping opencast embedding")
            return self.get_child_elements()[0]
        if self._page_type == IliasElementType.VIDEO_FOLDER_MAYBE_PAGINATED:
            log.explain("Unwrapping video pagination")
            return self._find_video_entries_paginated()[0]
        if self._contains_collapsed_future_meetings():
            log.explain("Requesting *all* future meetings")
            return self._uncollapse_future_meetings_url()
        return None

    def _is_forum_page(self) -> bool:
        read_more_btn = self._soup.find(
            "button",
            attrs={"onclick": lambda x: x and "cmdClass=ilobjforumgui&cmd=markAllRead" in x}
        )
        return read_more_btn is not None

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

    def _is_personal_desktop(self) -> bool:
        return self._soup.find("a", attrs={"href": lambda x: x and "block_type=pditems" in x})

    def _is_content_page(self) -> bool:
        link = self._soup.find(id="current_perma_link")
        if not link:
            return False
        return "target=copa_" in link.get("value")

    def _contains_collapsed_future_meetings(self) -> bool:
        return self._uncollapse_future_meetings_url() is not None

    def _uncollapse_future_meetings_url(self) -> Optional[IliasPageElement]:
        element = self._soup.find("a", attrs={"href": lambda x: x and "crs_next_sess=1" in x})
        if not element:
            return None
        link = self._abs_url_from_link(element)
        return IliasPageElement(IliasElementType.FOLDER, link, "show all meetings")

    def _player_to_video(self) -> List[IliasPageElement]:
        # Fetch the actual video page. This is a small wrapper page initializing a javscript
        # player. Sadly we can not execute that JS. The actual video stream url is nowhere
        # on the page, but defined in a JS object inside a script tag, passed to the player
        # library.
        # We do the impossible and RegEx the stream JSON object out of the page's HTML source
        regex = re.compile(
            r"({\"streams\"[\s\S]+?),\s*{\"paella_config_file", re.IGNORECASE
        )
        json_match = regex.search(str(self._soup))

        if json_match is None:
            log.warn("Could not find JSON stream info in video player. Ignoring video.")
            return []
        json_str = json_match.group(1)

        # parse it
        json_object = json.loads(json_str)
        streams = [stream for stream in json_object["streams"]]

        # and just fetch the lone video url!
        if len(streams) == 1:
            video_url = streams[0]["sources"]["mp4"][0]["src"]
            return [IliasPageElement(IliasElementType.VIDEO, video_url, self._source_name)]

        log.explain(f"Found multiple videos for stream at {self._source_name}")
        items = []
        for stream in sorted(streams, key=lambda stream: stream["content"]):
            full_name = f"{self._source_name.replace('.mp4', '')} ({stream['content']}).mp4"
            video_url = stream["sources"]["mp4"][0]["src"]
            items.append(IliasPageElement(IliasElementType.VIDEO, video_url, full_name))

        return items

    def _get_show_max_forum_entries_per_page_url(self) -> Optional[IliasPageElement]:
        correct_link = self._soup.find(
            "a",
            attrs={"href": lambda x: x and "trows=800" in x and "cmd=showThreads" in x}
        )

        if not correct_link:
            return None

        link = self._abs_url_from_link(correct_link)

        return IliasPageElement(IliasElementType.FORUM, link, "show all forum threads")

    def _find_personal_desktop_entries(self) -> List[IliasPageElement]:
        items: List[IliasPageElement] = []

        titles: List[Tag] = self._soup.select(".il-item-title")
        for title in titles:
            link = title.find("a")
            name = _sanitize_path_name(link.text.strip())
            url = self._abs_url_from_link(link)

            type = self._find_type_from_link(name, link, url)
            if not type:
                _unexpected_html_warning()
                log.warn_contd(f"Could not extract type for {link}")
                continue

            log.explain(f"Found {name!r}")

            if type == IliasElementType.FILE and "_download" not in url:
                url = re.sub(r"(target=file_\d+)", r"\1_download", url)
                log.explain("Rewired file URL to include download part")

            items.append(IliasPageElement(type, url, name))

        return items

    def _find_copa_entries(self) -> List[IliasPageElement]:
        items: List[IliasPageElement] = []
        links: List[Tag] = self._soup.findAll(class_="ilc_flist_a_FileListItemLink")

        for link in links:
            url = self._abs_url_from_link(link)
            name = _sanitize_path_name(link.getText().strip().replace("\t", ""))

            if "file_id" not in url:
                _unexpected_html_warning()
                log.warn_contd(f"Found unknown content page item {name!r} with url {url!r}")
                continue

            items.append(IliasPageElement(IliasElementType.FILE, url, name))

        return items

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
        # 6th or 7th child (1 indexed) is the modification time string. Try to find it
        # by parsing backwards from the end and finding something that looks like a date
        modification_time = None
        row: Tag = link.parent.parent.parent
        column_count = len(row.select("td.std"))
        for index in range(column_count, 0, -1):
            modification_string = link.parent.parent.parent.select_one(
                f"td.std:nth-child({index})"
            ).getText().strip()
            if re.search(r"\d+\.\d+.\d+ - \d+:\d+", modification_string):
                modification_time = datetime.strptime(modification_string, "%d.%m.%Y - %H:%M")
                break

        if modification_time is None:
            log.warn(f"Could not determine upload time for {link}")
            modification_time = datetime.now()

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

            name = _sanitize_path_name(children[1].getText().strip())
            log.explain(f"Found exercise detail entry {name!r}")

            for child in reversed(children):
                date = demangle_date(child.getText().strip(), fail_silently=True)
                if date is not None:
                    break
            if date is None:
                log.warn(f"Date parsing failed for exercise entry {name!r}")

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
                parent_container: Tag = listing.findParent(
                    "div", attrs={"class": lambda x: x and "form-group" in x}
                )
                label_container: Tag = parent_container.find(
                    attrs={"class": lambda x: x and "control-label" in x}
                )
                file_name = _sanitize_path_name(label_container.getText().strip())
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

            # The last meeting on every page is expanded by default.
            # Its content is then shown inline *and* in the meeting page itself.
            # We should skip the inline content.
            if element_type != IliasElementType.MEETING and self._is_in_expanded_meeting(link):
                continue

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

        result += self._find_cards()

        return result

    def _is_in_expanded_meeting(self, tag: Tag) -> bool:
        """
        Returns whether a file is part of an expanded meeting.
        Has false positives for meetings themselves as their title is also "in the expanded meeting content".
        It is in the same general div and this whole thing is guesswork.
        Therefore, you should check for meetings before passing them in this function.
        """
        parents: List[Tag] = list(tag.parents)
        for parent in parents:
            if not parent.get("class"):
                continue

            # We should not crawl files under meetings
            if "ilContainerListItemContentCB" in parent.get("class"):
                link: Tag = parent.parent.find("a")
                type = IliasPage._find_type_from_folder_like(link, self._page_url)
                return type == IliasElementType.MEETING

        return False

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
                    if prev.find("h3"):
                        found_titles.append(prev.find("h3").getText().strip())
                    else:
                        found_titles.append(prev.find("h2").getText().strip())

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

    def _find_cards(self) -> List[IliasPageElement]:
        result: List[IliasPageElement] = []

        card_titles: List[Tag] = self._soup.select(".card-title a")

        for title in card_titles:
            url = self._abs_url_from_link(title)
            name = _sanitize_path_name(title.getText().strip())
            type = self._find_type_from_card(title)

            if not type:
                _unexpected_html_warning()
                log.warn_contd(f"Could not extract type for {title}")
                continue

            result.append(IliasPageElement(type, url, name))

        card_button_tiles: List[Tag] = self._soup.select(".card-title button")

        for button in card_button_tiles:
            regex = re.compile(button["id"] + r".*window.open\(['\"](.+?)['\"]")
            res = regex.search(str(self._soup))
            if not res:
                _unexpected_html_warning()
                log.warn_contd(f"Could not find click handler target for {button}")
                continue
            url = self._abs_url_from_relative(res.group(1))
            name = _sanitize_path_name(button.getText().strip())
            type = self._find_type_from_card(button)
            caption_parent = button.findParent(
                "div",
                attrs={"class": lambda x: x and "caption" in x},
            )
            description = caption_parent.find_next_sibling("div").getText().strip()

            if not type:
                _unexpected_html_warning()
                log.warn_contd(f"Could not extract type for {button}")
                continue

            result.append(IliasPageElement(type, url, name, description=description))

        return result

    def _find_type_from_card(self, card_title: Tag) -> Optional[IliasElementType]:
        def is_card_root(element: Tag) -> bool:
            return "il-card" in element["class"] and "thumbnail" in element["class"]

        card_root: Optional[Tag] = None

        # We look for the card root
        for parent in card_title.parents:
            if is_card_root(parent):
                card_root = parent
                break

        if card_root is None:
            _unexpected_html_warning()
            log.warn_contd(f"Tried to figure out element type, but did not find an icon for {card_title}")
            return None

        icon: Tag = card_root.select_one(".il-card-repository-head .icon")

        if "opencast" in icon["class"]:
            return IliasElementType.VIDEO_FOLDER_MAYBE_PAGINATED
        if "exc" in icon["class"]:
            return IliasElementType.EXERCISE
        if "webr" in icon["class"]:
            return IliasElementType.LINK
        if "book" in icon["class"]:
            return IliasElementType.BOOKING
        if "frm" in icon["class"]:
            return IliasElementType.FORUM
        if "sess" in icon["class"]:
            return IliasElementType.MEETING
        if "tst" in icon["class"]:
            return IliasElementType.TEST
        if "fold" in icon["class"]:
            return IliasElementType.FOLDER
        if "copa" in icon["class"]:
            return IliasElementType.FOLDER
        if "svy" in icon["class"]:
            return IliasElementType.SURVEY

        _unexpected_html_warning()
        log.warn_contd(f"Could not extract type from {icon} for card title {card_title}")
        return None

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

        if "target=grp_" in parsed_url.query:
            return IliasElementType.FOLDER

        if "target=crs_" in parsed_url.query:
            return IliasElementType.FOLDER

        if "baseClass=ilExerciseHandlerGUI" in parsed_url.query:
            return IliasElementType.EXERCISE

        if "baseClass=ilLinkResourceHandlerGUI" in parsed_url.query and "calldirectlink" in parsed_url.query:
            return IliasElementType.LINK

        if "cmd=showThreads" in parsed_url.query or "target=frm_" in parsed_url.query:
            return IliasElementType.FORUM

        if "cmdClass=ilobjtestgui" in parsed_url.query:
            return IliasElementType.TEST

        # Booking and Meeting can not be detected based on the link. They do have a ref_id though, so
        # try to guess it from the image.

        # Everything with a ref_id can *probably* be opened to reveal nested things
        # video groups, directories, exercises, etc
        if "ref_id=" in parsed_url.query or "goto.php" in parsed_url.path:
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
            if "ilContainerListItemOuter" in parent["class"] or "il-std-item" in parent["class"]:
                found_parent = parent
                break

        if found_parent is None:
            _unexpected_html_warning()
            log.warn_contd(f"Tried to figure out element type, but did not find an icon for {url}")
            return None

        # Find the small descriptive icon to figure out the type
        img_tag: Optional[Tag] = found_parent.select_one("img.ilListItemIcon")

        if img_tag is None:
            img_tag = found_parent.select_one("img.icon")

        if img_tag is None and found_parent.find("a", attrs={"href": lambda x: x and "crs_next_sess=" in x}):
            log.explain("Found session expansion button, skipping it as it has no content")
            return None

        if img_tag is None:
            _unexpected_html_warning()
            log.warn_contd(f"Tried to figure out element type, but did not find an image for {url}")
            return None

        if "opencast" in str(img_tag["alt"]).lower():
            return IliasElementType.VIDEO_FOLDER_MAYBE_PAGINATED

        if str(img_tag["src"]).endswith("icon_exc.svg"):
            return IliasElementType.EXERCISE

        if str(img_tag["src"]).endswith("icon_webr.svg"):
            return IliasElementType.LINK

        if str(img_tag["src"]).endswith("icon_book.svg"):
            return IliasElementType.BOOKING

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

        # This checks whether we can reach a `:` without passing a `-`
        if re.search(r"^[^-]+: ", meeting_name):
            # Meeting name only contains date: "05. Jan 2000:"
            split_delimiter = ":"
        else:
            # Meeting name contains date and start/end times: "05. Jan 2000, 16:00 - 17:30:"
            split_delimiter = ", "

        # We have a meeting day without time
        date_portion_str = meeting_name.split(split_delimiter)[0]
        date_portion = demangle_date(date_portion_str)

        # We failed to parse the date, bail out
        if not date_portion:
            return meeting_name

        # Replace the first section with the absolute date
        rest_of_name = split_delimiter.join(meeting_name.split(split_delimiter)[1:])
        return datetime.strftime(date_portion, "%Y-%m-%d") + split_delimiter + rest_of_name

    def _abs_url_from_link(self, link_tag: Tag) -> str:
        """
        Create an absolute url from an <a> tag.
        """
        return self._abs_url_from_relative(link_tag.get("href"))

    def _abs_url_from_relative(self, relative_url: str) -> str:
        """
        Create an absolute url from a relative URL.
        """
        return urljoin(self._page_url, relative_url)


def _unexpected_html_warning() -> None:
    log.warn("Encountered unexpected HTML structure, ignoring element.")


german_months = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun', 'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez']
english_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def demangle_date(date_str: str, fail_silently: bool = False) -> Optional[datetime]:
    """
    Demangle a given date in one of the following formats (hour/minute part is optional):
    "Gestern, HH:MM"
    "Heute, HH:MM"
    "Morgen, HH:MM"
    "dd. mon yyyy, HH:MM
    """
    try:
        # Normalize whitespace because users
        date_str = re.sub(r"\s+", " ", date_str)

        date_str = re.sub("Gestern|Yesterday", _format_date_english(_yesterday()), date_str, re.I)
        date_str = re.sub("Heute|Today", _format_date_english(date.today()), date_str, re.I)
        date_str = re.sub("Morgen|Tomorrow",  _format_date_english(_tomorrow()), date_str, re.I)
        date_str = date_str.strip()
        for german, english in zip(german_months, english_months):
            date_str = date_str.replace(german, english)
            # Remove trailing dots for abbreviations, e.g. "20. Apr. 2020" -> "20. Apr 2020"
            date_str = date_str.replace(english + ".", english)

        # We now have a nice english String in the format: "dd. mmm yyyy, hh:mm" or "dd. mmm yyyy"

        # Check if we have a time as well
        if ", " in date_str:
            day_part, time_part = date_str.split(",")
        else:
            day_part = date_str.split(",")[0]
            time_part = None

        day_str, month_str, year_str = day_part.split(" ")

        day = int(day_str.strip().replace(".", ""))
        month = english_months.index(month_str.strip()) + 1
        year = int(year_str.strip())

        if time_part:
            hour_str, minute_str = time_part.split(":")
            hour = int(hour_str)
            minute = int(minute_str)
            return datetime(year, month, day, hour, minute)

        return datetime(year, month, day)
    except Exception:
        if not fail_silently:
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


def parse_ilias_forum_export(forum_export: BeautifulSoup) -> List[IliasForumThread]:
    elements = []
    for p in forum_export.select("body > p"):
        title_tag = p
        content_tag = p.find_next_sibling("ul")

        if not content_tag:
            # ILIAS allows users to delete the initial post while keeping the thread open
            # This produces empty threads without *any* content.
            # I am not sure why you would want this, but ILIAS makes it easy to do.
            continue

        title = p.find("b").text
        if ":" in title:
            title = title[title.find(":") + 1:]
        title = title.strip()
        mtime = _guess_timestamp_from_forum_post_content(content_tag)
        elements.append(IliasForumThread(title, title_tag, content_tag, mtime))

    return elements


def _guess_timestamp_from_forum_post_content(content: Tag) -> Optional[datetime]:
    posts: Optional[Tag] = content.select(".ilFrmPostHeader > span.small")
    if not posts:
        return None

    newest_date: Optional[datetime] = None

    for post in posts:
        text = post.text.strip()
        text = text[text.rfind("|") + 1:]
        date = demangle_date(text, fail_silently=True)
        if not date:
            continue

        if not newest_date or newest_date < date:
            newest_date = date

    return newest_date
