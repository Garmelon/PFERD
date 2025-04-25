import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Callable, Dict, Optional, Union, cast
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from PFERD.crawl import CrawlError
from PFERD.crawl.crawler import CrawlWarning
from PFERD.logging import log
from PFERD.utils import url_set_query_params

TargetType = Union[str, int]


class TypeMatcher:
    class UrlPath:
        path: str

        def __init__(self, path: str):
            self.path = path

    class UrlParameter:
        query: str

        def __init__(self, query: str):
            self.query = query

    class ImgSrc:
        src: str

        def __init__(self, src: str):
            self.src = src

    class ImgAlt:
        alt: str

        def __init__(self, alt: str):
            self.alt = alt

    class All:
        matchers: list['IliasElementMatcher']

        def __init__(self, matchers: list['IliasElementMatcher']):
            self.matchers = matchers

    class Any:
        matchers: list['IliasElementMatcher']

        def __init__(self, matchers: list['IliasElementMatcher']):
            self.matchers = matchers

    @staticmethod
    def path(path: str) -> UrlPath:
        return TypeMatcher.UrlPath(path)

    @staticmethod
    def query(query: str) -> UrlParameter:
        return TypeMatcher.UrlParameter(query)

    @staticmethod
    def img_src(src: str) -> ImgSrc:
        return TypeMatcher.ImgSrc(src)

    @staticmethod
    def img_alt(alt: str) -> ImgAlt:
        return TypeMatcher.ImgAlt(alt)

    @staticmethod
    def all(*matchers: 'IliasElementMatcher') -> All:
        return TypeMatcher.All(list(matchers))

    @staticmethod
    def any(*matchers: 'IliasElementMatcher') -> Any:
        return TypeMatcher.Any(list(matchers))

    @staticmethod
    def never() -> Any:
        return TypeMatcher.Any([])


IliasElementMatcher = (
    TypeMatcher.UrlPath
    | TypeMatcher.UrlParameter
    | TypeMatcher.ImgSrc
    | TypeMatcher.ImgAlt
    | TypeMatcher.All
    | TypeMatcher.Any
)


class IliasElementType(Enum):
    BLOG = "blog"
    BOOKING = "booking"
    COURSE = "course"
    DCL_RECORD_LIST = "dcl_record_list"
    EXERCISE_OVERVIEW = "exercise_overview"
    EXERCISE = "exercise"  # own submitted files
    EXERCISE_FILES = "exercise_files"  # own submitted files
    FILE = "file"
    FOLDER = "folder"
    FORUM = "forum"
    FORUM_THREAD = "forum_thread"
    INFO_TAB = "info_tab"
    LEARNING_MODULE = "learning_module"
    LEARNING_MODULE_HTML = "learning_module_html"
    LITERATURE_LIST = "literature_list"
    LINK = "link"
    MEDIA_POOL = "media_pool"
    MEDIACAST_VIDEO = "mediacast_video"
    MEDIACAST_VIDEO_FOLDER = "mediacast_video_folder"
    MEETING = "meeting"
    MOB_VIDEO = "mob_video"
    OPENCAST_VIDEO = "opencast_video"
    OPENCAST_VIDEO_FOLDER = "opencast_video_folder"
    OPENCAST_VIDEO_FOLDER_MAYBE_PAGINATED = "opencast_video_folder_maybe_paginated"
    OPENCAST_VIDEO_PLAYER = "opencast_video_player"
    SCORM_LEARNING_MODULE = "scorm_learning_module"
    SURVEY = "survey"
    TEST = "test"  # an online test. Will be ignored currently.
    WIKI = "wiki"

    def matcher(self) -> IliasElementMatcher:
        match self:
            case IliasElementType.BLOG:
                return TypeMatcher.any(
                    TypeMatcher.img_src("_blog.svg")
                )
            case IliasElementType.BOOKING:
                return TypeMatcher.any(
                    TypeMatcher.path("/book/"),
                    TypeMatcher.img_src("_book.svg")
                )
            case IliasElementType.COURSE:
                return TypeMatcher.any(TypeMatcher.path("/crs/"), TypeMatcher.img_src("_crsr.svg"))
            case IliasElementType.DCL_RECORD_LIST:
                return TypeMatcher.any(
                    TypeMatcher.img_src("_dcl.svg"),
                    TypeMatcher.query("cmdclass=ildclrecordlistgui")
                )
            case IliasElementType.EXERCISE:
                return TypeMatcher.never()
            case IliasElementType.EXERCISE_FILES:
                return TypeMatcher.never()
            case IliasElementType.EXERCISE_OVERVIEW:
                return TypeMatcher.any(
                    TypeMatcher.path("/exc/"),
                    TypeMatcher.path("_exc_"),
                    TypeMatcher.img_src("_exc.svg"),
                )
            case IliasElementType.FILE:
                return TypeMatcher.any(
                    TypeMatcher.query("cmd=sendfile"),
                    TypeMatcher.path("_file_"),
                    TypeMatcher.img_src("/filedelivery/"),
                )
            case IliasElementType.FOLDER:
                return TypeMatcher.any(
                    TypeMatcher.path("/fold/"),
                    TypeMatcher.img_src("_fold.svg"),

                    TypeMatcher.path("/grp/"),
                    TypeMatcher.img_src("_grp.svg"),

                    TypeMatcher.path("/copa/"),
                    TypeMatcher.path("_copa_"),
                    TypeMatcher.img_src("_copa.svg"),

                    # Not supported right now but warn users
                    # TypeMatcher.query("baseclass=ilmediapoolpresentationgui"),
                    # TypeMatcher.img_alt("medienpool"),
                    # TypeMatcher.img_src("_mep.svg"),
                )
            case IliasElementType.FORUM:
                return TypeMatcher.any(
                    TypeMatcher.path("/frm/"),
                    TypeMatcher.path("_frm_"),
                    TypeMatcher.img_src("_frm.svg"),
                )
            case IliasElementType.FORUM_THREAD:
                return TypeMatcher.never()
            case IliasElementType.INFO_TAB:
                return TypeMatcher.never()
            case IliasElementType.LITERATURE_LIST:
                return TypeMatcher.img_src("_bibl.svg")
            case IliasElementType.LEARNING_MODULE:
                return TypeMatcher.any(
                    TypeMatcher.path("/lm/"),
                    TypeMatcher.img_src("_lm.svg")
                )
            case IliasElementType.LEARNING_MODULE_HTML:
                return TypeMatcher.any(
                    TypeMatcher.query("baseclass=ilhtlmpresentationgui"),
                    TypeMatcher.img_src("_htlm.svg")
                )
            case IliasElementType.LINK:
                return TypeMatcher.any(
                    TypeMatcher.all(
                        TypeMatcher.query("baseclass=illinkresourcehandlergui"),
                        TypeMatcher.query("calldirectlink"),
                    ),
                    TypeMatcher.img_src("_webr.svg")
                )
            case IliasElementType.MEDIA_POOL:
                return TypeMatcher.any(
                    TypeMatcher.query("baseclass=ilmediapoolpresentationgui"),
                    TypeMatcher.img_src("_mep.svg")
                )
            case IliasElementType.MEDIACAST_VIDEO:
                return TypeMatcher.never()
            case IliasElementType.MEDIACAST_VIDEO_FOLDER:
                return TypeMatcher.any(
                    TypeMatcher.path("/mcst/"),
                    TypeMatcher.query("baseclass=ilmediacasthandlergui"),
                    TypeMatcher.img_src("_mcst.svg")
                )
            case IliasElementType.MEETING:
                return TypeMatcher.any(
                    TypeMatcher.img_src("_sess.svg")
                )
            case IliasElementType.MOB_VIDEO:
                return TypeMatcher.never()
            case IliasElementType.OPENCAST_VIDEO:
                return TypeMatcher.never()
            case IliasElementType.OPENCAST_VIDEO_FOLDER:
                return TypeMatcher.never()
            case IliasElementType.OPENCAST_VIDEO_FOLDER_MAYBE_PAGINATED:
                return TypeMatcher.img_alt("opencast")
            case IliasElementType.OPENCAST_VIDEO_PLAYER:
                return TypeMatcher.never()
            case IliasElementType.SCORM_LEARNING_MODULE:
                return TypeMatcher.any(
                    TypeMatcher.query("baseclass=ilsahspresentationgui"),
                    TypeMatcher.img_src("_sahs.svg")
                )
            case IliasElementType.SURVEY:
                return TypeMatcher.any(
                    TypeMatcher.path("/svy/"),
                    TypeMatcher.img_src("svy.svg")
                )
            case IliasElementType.TEST:
                return TypeMatcher.any(
                    TypeMatcher.query("cmdclass=ilobjtestgui"),
                    TypeMatcher.query("cmdclass=iltestscreengui"),
                    TypeMatcher.img_src("_tst.svg")
                )
            case IliasElementType.WIKI:
                return TypeMatcher.any(
                    TypeMatcher.query("baseClass=ilwikihandlergui"),
                    TypeMatcher.img_src("wiki.svg")
                )

        raise CrawlWarning(f"Unknown matcher {self}")


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
            r"book/(?P<id>\d+)",  # booking
            r"cat/(?P<id>\d+)",
            r"copa/(?P<id>\d+)",  # content page
            r"crs/(?P<id>\d+)",  # course
            r"exc/(?P<id>\d+)",  # exercise
            r"file/(?P<id>\d+)",  # file
            r"fold/(?P<id>\d+)",  # folder
            r"frm/(?P<id>\d+)",  # forum
            r"grp/(?P<id>\d+)",  # group
            r"lm/(?P<id>\d+)",  # learning module
            r"mcst/(?P<id>\d+)",  # mediacast
            r"pg/(?P<id>(\d|_)+)",  # page?
            r"svy/(?P<id>\d+)",  # survey
            r"sess/(?P<id>\d+)",  # session
            r"webr/(?P<id>\d+)",  # web referene (link)
            r"thr_pk=(?P<id>\d+)",  # forums
            r"ref_id=(?P<id>\d+)",
            r"target=[a-z]+_(?P<id>\d+)",
            r"mm_(?P<id>\d+)"
        ]

        for regex in regexes:
            if match := re.search(regex, self.url):
                return match.groupdict()["id"]

        # Fall back to URL
        log.warn(f"Didn't find identity for {self.name} - {self.url}. Please report this.")
        return self.url

    @staticmethod
    def create_new(
        typ: IliasElementType,
        url: str,
        name: str,
        mtime: Optional[datetime] = None,
        description: Optional[str] = None,
        skip_sanitize: bool = False
    ) -> 'IliasPageElement':
        if typ == IliasElementType.MEETING:
            normalized = IliasPageElement._normalize_meeting_name(name)
            log.explain(f"Normalized meeting name from {name!r} to {normalized!r}")
            name = normalized

        if not skip_sanitize:
            name = _sanitize_path_name(name)

        return IliasPageElement(typ, url, name, mtime, description)

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


@dataclass
class IliasDownloadForumData:
    url: str
    form_data: Dict[str, Union[str, list[str]]]
    empty: bool


@dataclass
class IliasForumThread:
    name: str
    name_tag: Tag
    content_tag: Tag
    mtime: Optional[datetime]


@dataclass
class IliasLearningModulePage:
    title: str
    content: Tag
    next_url: Optional[str]
    previous_url: Optional[str]


class IliasSoup:
    soup: BeautifulSoup
    page_url: str

    def __init__(self, soup: BeautifulSoup, page_url: str):
        self.soup = soup
        self.page_url = page_url


class IliasPage:

    def __init__(self, ilias_soup: IliasSoup, source_element: Optional[IliasPageElement]):
        self._ilias_soup = ilias_soup
        self._soup = ilias_soup.soup
        self._page_url = ilias_soup.page_url
        self._page_type = source_element.type if source_element else None
        self._source_name = source_element.name if source_element else ""

    @staticmethod
    def is_root_page(soup: IliasSoup) -> bool:
        if permalink := IliasPage.get_soup_permalink(soup):
            return "goto.php/root/" in permalink
        return False

    def get_child_elements(self) -> list[IliasPageElement]:
        """
        Return all child page elements you can find here.
        """
        if self._is_video_player():
            log.explain("Page is a video player, extracting URL")
            return self._player_to_video()
        if self._is_opencast_video_listing():
            log.explain("Page is an opencast video listing, searching for elements")
            return self._find_opencast_video_entries()
        if self._is_exercise_file():
            log.explain("Page is an exercise, searching for elements")
            return self._find_exercise_entries()
        if self._is_personal_desktop():
            log.explain("Page is the personal desktop, searching for elements")
            return self._find_personal_desktop_entries()
        if self._is_content_page():
            log.explain("Page is a content page, searching for elements")
            return self._find_copa_entries()
        if self._is_info_tab():
            log.explain("Page is info tab, searching for elements")
            return self._find_info_tab_entries()
        log.explain("Page is a normal folder, searching for elements")
        return self._find_normal_entries()

    def get_info_tab(self) -> Optional[IliasPageElement]:
        tab: Optional[Tag] = cast(Optional[Tag], self._soup.find(
            name="a",
            attrs={"href": lambda x: x is not None and "cmdClass=ilinfoscreengui" in x}
        ))
        if tab is not None:
            return IliasPageElement.create_new(
                IliasElementType.INFO_TAB,
                self._abs_url_from_link(tab),
                "infos"
            )
        return None

    def get_description(self) -> Optional[BeautifulSoup]:
        def is_interesting_class(name: str) -> bool:
            return name in [
                "ilCOPageSection", "ilc_Paragraph", "ilc_va_ihcap_VAccordIHeadCap",
                "ilc_va_ihcap_AccordIHeadCap", "ilc_media_cont_MediaContainer"
            ]

        paragraphs: list[Tag] = cast(list[Tag], self._soup.find_all(class_=is_interesting_class))
        if not paragraphs:
            return None

        # Extract bits and pieces into a string and parse it again.
        # This ensures we don't miss anything and weird structures are resolved
        # somewhat gracefully.
        raw_html = ""
        for p in paragraphs:
            if p.find_parent(class_=is_interesting_class):
                continue
            if "ilc_media_cont_MediaContainer" in p["class"]:
                # We have an embedded video which should be downloaded by _find_mob_videos
                if video := p.select_one("video"):
                    url, title = self._find_mob_video_url_title(video, p)
                    raw_html += '<div style="min-width: 100px; min-height: 100px; border: 1px solid black;'
                    raw_html += 'display: flex; justify-content: center; align-items: center;'
                    raw_html += ' margin: 0.5rem;">'
                    if url is not None and urlparse(url).hostname != urlparse(self._page_url).hostname:
                        if url.startswith("//"):
                            url = "https:" + url
                        raw_html += f'<a href="{url}" target="_blank">External Video: {title}</a>'
                    else:
                        raw_html += f"Video elided. Filename: '{title}'."
                    raw_html += "</div>\n"
                    continue

            # Ignore special listings (like folder groupings)
            if "ilc_section_Special" in p["class"]:
                continue

            raw_html += str(p) + "\n"
        raw_html = f"<body>\n{raw_html}\n</body>"

        return BeautifulSoup(raw_html, "html.parser")

    def get_learning_module_data(self) -> Optional[IliasLearningModulePage]:
        if not self._is_learning_module_page():
            return None
        content = cast(Tag, self._soup.select_one("#ilLMPageContent"))
        title = cast(Tag, self._soup.select_one(".ilc_page_title_PageTitle")).get_text().strip()
        return IliasLearningModulePage(
            title=title,
            content=content,
            next_url=self._find_learning_module_next(),
            previous_url=self._find_learning_module_prev()
        )

    def _find_learning_module_next(self) -> Optional[str]:
        for link in self._soup.select("a.ilc_page_rnavlink_RightNavigationLink"):
            url = self._abs_url_from_link(link)
            if "baseClass=ilLMPresentationGUI" not in url:
                continue
            return url
        return None

    def _find_learning_module_prev(self) -> Optional[str]:
        for link in self._soup.select("a.ilc_page_lnavlink_LeftNavigationLink"):
            url = self._abs_url_from_link(link)
            if "baseClass=ilLMPresentationGUI" not in url:
                continue
            return url
        return None

    def get_forum_export_url(self) -> Optional[str]:
        forum_link = self._soup.select_one("#tab_forums_threads > a")
        if not forum_link:
            log.explain("Found no forum link")
            return None

        base_url = self._abs_url_from_link(forum_link)
        base_url = re.sub(r"cmd=\w+", "cmd=post", base_url)
        base_url = re.sub(r"cmdClass=\w+", "cmdClass=ilExportGUI", base_url)

        rtoken_form = cast(
            Optional[Tag],
            self._soup.find("form", attrs={"action": lambda x: x is not None and "rtoken=" in x})
        )
        if not rtoken_form:
            log.explain("Found no rtoken anywhere")
            return None
        match = cast(re.Match[str], re.search(r"rtoken=(\w+)", str(rtoken_form.attrs["action"])))
        rtoken = match.group(1)

        base_url = base_url + "&rtoken=" + rtoken

        return base_url

    def get_next_stage_element(self) -> Optional[IliasPageElement]:
        if self._is_ilias_opencast_embedding():
            log.explain("Unwrapping opencast embedding")
            return self.get_child_elements()[0]
        if self._page_type == IliasElementType.OPENCAST_VIDEO_FOLDER_MAYBE_PAGINATED:
            log.explain("Unwrapping video pagination")
            return self._find_opencast_video_entries_paginated()[0]
        if self._contains_collapsed_future_meetings():
            log.explain("Requesting *all* future meetings")
            return self._uncollapse_future_meetings_url()
        if self._is_exercise_not_all_shown():
            return self._show_all_exercises()
        if not self._is_content_tab_selected():
            if self._page_type != IliasElementType.INFO_TAB:
                log.explain("Selecting content tab")
                return self._select_content_page_url()
            else:
                log.explain("Crawling info tab, skipping content select")
        return None

    def _is_video_player(self) -> bool:
        return "paella_config_file" in str(self._soup)

    def _is_opencast_video_listing(self) -> bool:
        if self._is_ilias_opencast_embedding():
            return True

        # Raw listing without ILIAS fluff
        video_element_table = self._soup.find(
            name="table", id=re.compile(r"tbl_xoct_.+")
        )
        return video_element_table is not None

    def _is_ilias_opencast_embedding(self) -> bool:
        # ILIAS fluff around the real opencast html
        if self._soup.find(id="headerimage"):
            element: Tag = cast(Tag, self._soup.find(id="headerimage"))
            if "opencast" in cast(str, element.attrs["src"]).lower():
                return True
        return False

    def _is_exercise_file(self) -> bool:
        # we know it from before
        if self._page_type == IliasElementType.EXERCISE_OVERVIEW:
            return True

        # We have no suitable parent - let's guesss
        if self._soup.find(id="headerimage"):
            element: Tag = cast(Tag, self._soup.find(id="headerimage"))
            if "exc" in cast(str, element.attrs["src"]).lower():
                return True

        return False

    def _is_personal_desktop(self) -> bool:
        return "baseclass=ildashboardgui" in self._page_url.lower() and "&cmd=show" in self._page_url.lower()

    def _is_content_page(self) -> bool:
        if link := self.get_permalink():
            return "/copa/" in link
        return False

    def _is_learning_module_page(self) -> bool:
        if link := self.get_permalink():
            return "target=pg_" in link
        return False

    def _contains_collapsed_future_meetings(self) -> bool:
        return self._uncollapse_future_meetings_url() is not None

    def _uncollapse_future_meetings_url(self) -> Optional[IliasPageElement]:
        element = cast(Optional[Tag], self._soup.find(
            "a",
            attrs={"href": lambda x: x is not None and ("crs_next_sess=1" in x or "crs_prev_sess=1" in x)}
        ))
        if not element:
            return None
        link = self._abs_url_from_link(element)
        return IliasPageElement.create_new(IliasElementType.FOLDER, link, "show all meetings")

    def _is_exercise_not_all_shown(self) -> bool:
        return (self._page_type == IliasElementType.EXERCISE_OVERVIEW
                and "mode=all" not in self._page_url.lower())

    def _show_all_exercises(self) -> Optional[IliasPageElement]:
        return IliasPageElement.create_new(
            IliasElementType.EXERCISE_OVERVIEW,
            self._page_url + "&mode=all",
            "show all exercises"
        )

    def _is_content_tab_selected(self) -> bool:
        return self._select_content_page_url() is None

    def _is_info_tab(self) -> bool:
        might_be_info = self._soup.find("form", attrs={"name": lambda x: x == "formInfoScreen"}) is not None
        return self._page_type == IliasElementType.INFO_TAB and might_be_info

    def _is_course_overview_page(self) -> bool:
        return "baseClass=ilmembershipoverviewgui" in self._page_url

    def _select_content_page_url(self) -> Optional[IliasPageElement]:
        tab = cast(Optional[Tag], self._soup.find(
            id="tab_view_content",
            attrs={"class": lambda x: x is not None and "active" not in x}
        ))
        # Already selected (or not found)
        if not tab:
            return None
        link = cast(Optional[Tag], tab.find("a"))
        if link:
            link_str = self._abs_url_from_link(link)
            return IliasPageElement.create_new(IliasElementType.FOLDER, link_str, "select content page")

        _unexpected_html_warning()
        log.warn_contd(f"Could not find content tab URL on {self._page_url!r}.")
        log.warn_contd("PFERD might not find content on the course's main page.")
        return None

    def _player_to_video(self) -> list[IliasPageElement]:
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
            return [
                IliasPageElement.create_new(IliasElementType.OPENCAST_VIDEO, video_url, self._source_name)
            ]

        log.explain(f"Found multiple videos for stream at {self._source_name}")
        items = []
        for stream in sorted(streams, key=lambda stream: stream["content"]):
            full_name = f"{self._source_name.replace('.mp4', '')} ({stream['content']}).mp4"
            video_url = stream["sources"]["mp4"][0]["src"]
            items.append(IliasPageElement.create_new(IliasElementType.OPENCAST_VIDEO, video_url, full_name))

        return items

    def _get_show_max_forum_entries_per_page_url(
        self, wanted_max: Optional[int] = None
    ) -> Optional[IliasPageElement]:
        correct_link = cast(Optional[Tag], self._soup.find(
            "a",
            attrs={"href": lambda x: x is not None and "trows=800" in x and "cmd=showThreads" in x}
        ))

        if not correct_link:
            return None

        link = self._abs_url_from_link(correct_link)
        if wanted_max is not None:
            link = link.replace("trows=800", f"trows={wanted_max}")

        return IliasPageElement.create_new(IliasElementType.FORUM, link, "show all forum threads")

    def _get_forum_thread_count(self) -> Optional[int]:
        log.explain_topic("Trying to find forum thread count")

        candidates = cast(list[Tag], self._soup.select(".ilTableFootLight"))
        extract_regex = re.compile(r"\s(?P<max>\d+)\s*\)")

        for candidate in candidates:
            log.explain(f"Found thread count candidate: {candidate}")
            if match := extract_regex.search(candidate.get_text()):
                return int(match.group("max"))
        else:
            log.explain("Found no candidates to extract thread count from")

        return None

    def _find_personal_desktop_entries(self) -> list[IliasPageElement]:
        items: list[IliasPageElement] = []

        titles: list[Tag] = self._soup.select("#block_pditems_0 .il-item-title")
        for title in titles:
            link = cast(Optional[Tag], title.find("a"))

            if not link:
                log.explain(f"Skipping offline item: {title.get_text().strip()!r}")
                continue

            name = _sanitize_path_name(link.text.strip())
            url = self._abs_url_from_link(link)

            if "cmd=manage" in url and "cmdClass=ilPDSelectedItemsBlockGUI" in url:
                # Configure button/link does not have anything interesting
                continue

            typ = IliasPage._find_type_for_element(
                name, url, lambda: IliasPage._find_icon_for_folder_entry(link)
            )
            if not typ:
                _unexpected_html_warning()
                log.warn_contd(f"Could not extract type for {link}")
                continue

            log.explain(f"Found {name!r} of type {typ}")

            items.append(IliasPageElement.create_new(typ, url, name))

        return items

    def _find_copa_entries(self) -> list[IliasPageElement]:
        items: list[IliasPageElement] = []
        links: list[Tag] = cast(list[Tag], self._soup.find_all(class_="ilc_flist_a_FileListItemLink"))

        for link in links:
            url = self._abs_url_from_link(link)
            name = re.sub(r"\([\d,.]+ [MK]B\)", "", link.get_text()).strip().replace("\t", "")
            name = _sanitize_path_name(name)

            if "file_id" not in url:
                _unexpected_html_warning()
                log.warn_contd(f"Found unknown content page item {name!r} with url {url!r}")
                continue

            items.append(IliasPageElement.create_new(IliasElementType.FILE, url, name))

        return items

    def _find_info_tab_entries(self) -> list[IliasPageElement]:
        items = []
        links: list[Tag] = self._soup.select("a.il_ContainerItemCommand")

        for link in links:
            if "cmdClass=ilobjcoursegui" not in link["href"]:
                continue
            if "cmd=sendfile" not in link["href"]:
                continue
            items.append(IliasPageElement.create_new(
                IliasElementType.FILE,
                self._abs_url_from_link(link),
                _sanitize_path_name(link.get_text())
            ))

        return items

    def _find_opencast_video_entries(self) -> list[IliasPageElement]:
        # ILIAS has three stages for video pages
        # 1. The initial dummy page without any videos. This page contains the link to the listing
        # 2. The video listing which might be paginated
        # 3. An unpaginated video listing (or at least one that includes 800 videos)
        #
        # We need to figure out where we are.

        video_element_table = cast(Optional[Tag], self._soup.find(
            name="table", id=re.compile(r"tbl_xoct_.+")
        ))

        if video_element_table is None:
            # We are in stage 1
            # The page is actually emtpy but contains the link to stage 2
            content_link: Tag = cast(Tag, self._soup.select_one("#tab_series a"))
            url: str = self._abs_url_from_link(content_link)
            query_params = {"limit": "800", "cmd": "asyncGetTableGUI", "cmdMode": "asynch"}
            url = url_set_query_params(url, query_params)
            log.explain("Found ILIAS video frame page, fetching actual content next")
            return [
                IliasPageElement.create_new(IliasElementType.OPENCAST_VIDEO_FOLDER_MAYBE_PAGINATED, url, "")
            ]

        is_paginated = self._soup.find(id=re.compile(r"tab_page_sel.+")) is not None

        if is_paginated and not self._page_type == IliasElementType.OPENCAST_VIDEO_FOLDER:
            # We are in stage 2 - try to break pagination
            return self._find_opencast_video_entries_paginated()

        return self._find_opencast_video_entries_no_paging()

    def _find_opencast_video_entries_paginated(self) -> list[IliasPageElement]:
        table_element = cast(Optional[Tag], self._soup.find(name="table", id=re.compile(r"tbl_xoct_.+")))

        if table_element is None:
            log.warn("Couldn't increase elements per page (table not found). I might miss elements.")
            return self._find_opencast_video_entries_no_paging()

        id_match = re.match(r"tbl_xoct_(.+)", cast(str, table_element.attrs["id"]))
        if id_match is None:
            log.warn("Couldn't increase elements per page (table id not found). I might miss elements.")
            return self._find_opencast_video_entries_no_paging()

        table_id = id_match.group(1)

        query_params = {f"tbl_xoct_{table_id}_trows": "800",
                        "cmd": "asyncGetTableGUI", "cmdMode": "asynch"}
        url = url_set_query_params(self._page_url, query_params)

        log.explain("Disabled pagination, retrying folder as a new entry")
        return [IliasPageElement.create_new(IliasElementType.OPENCAST_VIDEO_FOLDER, url, "")]

    def _find_opencast_video_entries_no_paging(self) -> list[IliasPageElement]:
        """
        Crawls the "second stage" video page. This page contains the actual video urls.
        """
        # Video start links are marked with an "Abspielen" link
        video_links = cast(list[Tag], self._soup.find_all(
            name="a", text=re.compile(r"\s*(Abspielen|Play)\s*")
        ))

        results: list[IliasPageElement] = []

        for link in video_links:
            results.append(self._listed_opencast_video_to_element(link))

        return results

    def _listed_opencast_video_to_element(self, link: Tag) -> IliasPageElement:
        # The link is part of a table with multiple columns, describing metadata.
        # 6th or 7th child (1 indexed) is the modification time string. Try to find it
        # by parsing backwards from the end and finding something that looks like a date
        modification_time = None
        row: Tag = link.parent.parent.parent  # type: ignore
        column_count = len(row.select("td.std"))
        for index in range(column_count, 0, -1):
            modification_string = link.parent.parent.parent.select_one(  # type: ignore
                f"td.std:nth-child({index})"
            ).get_text().strip()
            if match := re.search(r"\d+\.\d+.\d+ \d+:\d+", modification_string):
                modification_time = datetime.strptime(match.group(0), "%d.%m.%Y %H:%M")
                break

        if modification_time is None:
            log.warn(f"Could not determine upload time for {link}")
            modification_time = datetime.now()

        title = link.parent.parent.parent.select_one("td.std:nth-child(3)").get_text().strip()  # type: ignore
        title += ".mp4"

        video_name: str = _sanitize_path_name(title)

        video_url = self._abs_url_from_link(link)

        log.explain(f"Found video {video_name!r} at {video_url}")
        return IliasPageElement.create_new(
            IliasElementType.OPENCAST_VIDEO_PLAYER, video_url, video_name, modification_time
        )

    def _find_exercise_entries(self) -> list[IliasPageElement]:
        if self._soup.find(id="tab_submission"):
            log.explain("Found submission tab. This is an exercise detail or files page")
            if self._soup.select_one("#tab_submission.active") is None:
                log.explain("  This is a details page")
                return self._find_exercise_entries_detail_page()
            else:
                log.explain("  This is a files page")
                return self._find_exercise_entries_files_page()

        log.explain("Found no submission tab. This is an exercise root page")
        return self._find_exercise_entries_root_page()

    def _find_exercise_entries_detail_page(self) -> list[IliasPageElement]:
        results: list[IliasPageElement] = []

        if link := cast(Optional[Tag], self._soup.select_one("#tab_submission > a")):
            results.append(IliasPageElement.create_new(
                IliasElementType.EXERCISE_FILES,
                self._abs_url_from_link(link),
                "Submission"
            ))
        else:
            log.explain("Found no submission link for exercise, maybe it has not started yet?")

        # Find all download links in the container (this will contain all the *feedback* files)
        download_links = cast(list[Tag], self._soup.find_all(
            name="a",
            # download links contain the given command class
            attrs={"href": lambda x: x is not None and "cmd=download" in x},
            text="Download"
        ))

        for link in download_links:
            parent_row: Tag = cast(Tag, link.find_parent(
                attrs={"class": lambda x: x is not None and "row" in x}))
            name_tag = cast(Optional[Tag], parent_row.find(name="div"))

            if not name_tag:
                log.warn("Could not find name tag for exercise entry")
                _unexpected_html_warning()
                continue

            name = _sanitize_path_name(name_tag.get_text().strip())
            log.explain(f"Found exercise detail entry {name!r}")

            results.append(IliasPageElement.create_new(
                IliasElementType.FILE,
                self._abs_url_from_link(link),
                name
            ))

        return results

    def _find_exercise_entries_files_page(self) -> list[IliasPageElement]:
        results: list[IliasPageElement] = []

        # Find all download links in the container
        download_links = cast(list[Tag], self._soup.find_all(
            name="a",
            # download links contain the given command class
            attrs={"href": lambda x: x is not None and "cmd=download" in x},
            text="Download"
        ))

        for link in download_links:
            parent_row: Tag = cast(Tag, link.find_parent("tr"))
            children = cast(list[Tag], parent_row.find_all("td"))

            name = _sanitize_path_name(children[1].get_text().strip())
            log.explain(f"Found exercise file entry {name!r}")

            date = None
            for child in reversed(children):
                date = demangle_date(child.get_text().strip(), fail_silently=True)
                if date is not None:
                    break
            if date is None:
                log.warn(f"Date parsing failed for exercise file entry {name!r}")

            results.append(IliasPageElement.create_new(
                IliasElementType.FILE,
                self._abs_url_from_link(link),
                name,
                date
            ))

        return results

    def _find_exercise_entries_root_page(self) -> list[IliasPageElement]:
        results: list[IliasPageElement] = []

        content_tab = cast(Optional[Tag], self._soup.find(id="ilContentContainer"))
        if not content_tab:
            log.warn("Could not find content tab in exercise overview page")
            _unexpected_html_warning()
            return []

        individual_exercises = content_tab.find_all(
            name="a",
            attrs={
                "href": lambda x: x is not None
                and "ass_id=" in x
                and "cmdClass=ilAssignmentPresentationGUI" in x
            }
        )

        for exercise in cast(list[Tag], individual_exercises):
            name = _sanitize_path_name(exercise.get_text().strip())
            results.append(IliasPageElement.create_new(
                IliasElementType.EXERCISE,
                self._abs_url_from_link(exercise),
                name
            ))

        for result in results:
            log.explain(f"Found exercise {result.name!r}")

        return results

    def _find_normal_entries(self) -> list[IliasPageElement]:
        result: list[IliasPageElement] = []

        links: list[Tag] = []
        # Fetch all links and throw them to the general interpreter
        if self._is_course_overview_page():
            log.explain("Page is a course overview page, adjusting link selector")
            links.extend(self._soup.select(".il-item-title > a"))
        else:
            links.extend(self._soup.select("a.il_ContainerItemTitle"))

        for link in links:
            abs_url = self._abs_url_from_link(link)
            # Make sure parents are sanitized. We do not want accidental parents
            parents = [_sanitize_path_name(x) for x in IliasPage._find_upwards_folder_hierarchy(link)]

            if parents:
                element_name = "/".join(parents) + "/" + _sanitize_path_name(link.get_text())
            else:
                element_name = _sanitize_path_name(link.get_text())

            element_type = IliasPage._find_type_for_element(
                element_name, abs_url, lambda: IliasPage._find_icon_for_folder_entry(link)
            )
            description = IliasPage._find_link_description(link)

            # The last meeting on every page is expanded by default.
            # Its content is then shown inline *and* in the meeting page itself.
            # We should skip the inline content.
            if element_type != IliasElementType.MEETING and self._is_in_expanded_meeting(link):
                continue

            if not element_type:
                continue
            elif element_type == IliasElementType.FILE:
                result.append(IliasPage._file_to_element(element_name, abs_url, link))
                continue

            log.explain(f"Found {element_name!r} of type {element_type}")
            result.append(IliasPageElement.create_new(
                element_type,
                abs_url,
                element_name,
                description=description,
                skip_sanitize=True
            ))

        result += self._find_cards()
        result += self._find_mediacast_videos()
        result += self._find_mob_videos()

        return result

    def _find_mediacast_videos(self) -> list[IliasPageElement]:
        videos: list[IliasPageElement] = []

        regex = re.compile(r"il\.VideoPlaylist\.init.+?\[(.+?)], ")
        for script in cast(list[Tag], self._soup.find_all("script")):
            for match in regex.finditer(script.text):
                try:
                    playlist = json.loads("[" + match.group(1) + "]")
                except json.JSONDecodeError:
                    log.warn("Could not decode playlist json")
                    log.warn_contd(f"Playlist json: [{match.group(1)}]")
                    continue
                for elem in playlist:
                    title = elem.get("title", None)
                    description = elem.get("description", None)
                    url = elem.get("resource", None)
                    if title is None or description is None or url is None:
                        log.explain(f"Mediacast json: {match.group(1)}")
                        log.warn("Mediacast video json was not complete")
                    if title is None:
                        log.warn_contd("Missing title")
                    if description is None:
                        log.warn_contd("Missing description")
                    if url is None:
                        log.warn_contd("Missing URL")

                    if not title.endswith(".mp4") and not title.endswith(".webm"):
                        # just to make sure it has some kinda-alrightish ending
                        title = title + ".mp4"
                    videos.append(IliasPageElement.create_new(
                        typ=IliasElementType.MEDIACAST_VIDEO,
                        url=self._abs_url_from_relative(cast(str, url)),
                        name=_sanitize_path_name(title)
                    ))

        return videos

    def _find_mob_videos(self) -> list[IliasPageElement]:
        videos: list[IliasPageElement] = []

        selector = "figure.ilc_media_cont_MediaContainerHighlighted,figure.ilc_media_cont_MediaContainer"
        for figure in self._soup.select(selector):
            video_element = figure.select_one("video")
            if not video_element:
                continue

            url, title = self._find_mob_video_url_title(video_element, figure)

            if url is None:
                _unexpected_html_warning()
                log.warn_contd(f"No <source> element found for mob video '{title}'")
                continue

            if urlparse(url).hostname != urlparse(self._page_url).hostname:
                log.explain(f"Found external video at {url}, ignoring")
                continue

            videos.append(IliasPageElement.create_new(
                typ=IliasElementType.MOB_VIDEO,
                url=url,
                name=_sanitize_path_name(title),
                mtime=None
            ))

        return videos

    def _find_mob_video_url_title(self, video_element: Tag, figure: Tag) -> tuple[Optional[str], str]:
        url = None
        for source in video_element.select("source"):
            if source.get("type", "") == "video/mp4":
                url = cast(Optional[str], source.get("src"))
                break

        if url is None and video_element.get("src"):
            url = cast(Optional[str], video_element.get("src"))

        fig_caption = cast(Optional[Tag], figure.select_one("figcaption"))
        if fig_caption:
            title = cast(Tag, figure.select_one("figcaption")).get_text().strip() + ".mp4"
        elif url is not None:
            path = urlparse(self._abs_url_from_relative(url)).path
            title = path.rsplit("/", 1)[-1]
        else:
            title = f"unknown video {figure}"

        if url:
            url = self._abs_url_from_relative(url)

        return url, title

    def _is_in_expanded_meeting(self, tag: Tag) -> bool:
        """
        Returns whether a file is part of an expanded meeting.
        Has false positives for meetings themselves as their title is also "in the expanded meeting content".
        It is in the same general div and this whole thing is guesswork.
        Therefore, you should check for meetings before passing them in this function.
        """
        parents: list[Tag] = list(tag.parents)
        for parent in parents:
            if not parent.get("class"):
                continue

            # We should not crawl files under meetings
            if "ilContainerListItemContentCB" in cast(str, parent.get("class")):
                link: Tag = parent.parent.find("a")  # type: ignore
                typ = IliasPage._find_type_for_element(
                    "meeting",
                    self._abs_url_from_link(link),
                    lambda: IliasPage._find_icon_for_folder_entry(link)
                )
                return typ == IliasElementType.MEETING

        return False

    @staticmethod
    def _find_upwards_folder_hierarchy(tag: Tag) -> list[str]:
        """
        Interprets accordions and expandable blocks as virtual folders and returns them
        in order. This allows us to find a file named "Test" in an accordion "Acc" as "Acc/Test"
        """
        found_titles = []

        outer_accordion_content: Optional[Tag] = None

        parents: list[Tag] = list(tag.parents)
        for parent in parents:
            if not parent.get("class"):
                continue

            # ILIAS has proper accordions and weird blocks that look like normal headings,
            # but some JS later transforms them into an accordion.

            # This is for these weird JS-y blocks and custom item groups
            if "ilContainerItemsContainer" in cast(str, parent.get("class")):
                data_store_url = parent.parent.get("data-store-url", "").lower()  # type: ignore
                is_custom_item_group = "baseclass=ilcontainerblockpropertiesstoragegui" in data_store_url \
                                       and "cont_block_id=" in data_store_url
                # I am currently under the impression that *only* those JS blocks have an
                # ilNoDisplay class.
                if not is_custom_item_group and "ilNoDisplay" not in cast(str, parent.get("class")):
                    continue
                prev = cast(Tag, parent.find_previous_sibling("div"))
                if "ilContainerBlockHeader" in cast(str, prev.get("class")):
                    if prev.find("h3"):
                        found_titles.append(cast(Tag, prev.find("h3")).get_text().strip())
                    else:
                        found_titles.append(cast(Tag, prev.find("h2")).get_text().strip())

            # And this for real accordions
            if "il_VAccordionContentDef" in cast(str, parent.get("class")):
                outer_accordion_content = parent
                break

        if outer_accordion_content:
            accordion_tag = cast(Tag, outer_accordion_content.parent)
            head_tag = cast(Tag, accordion_tag.find(attrs={
                "class": lambda x: x is not None and (
                    "ilc_va_ihead_VAccordIHead" in x or "ilc_va_ihead_AccordIHead" in x
                )
            }))
            found_titles.append(head_tag.get_text().strip())

        return [_sanitize_path_name(x) for x in reversed(found_titles)]

    @staticmethod
    def _find_link_description(link: Tag) -> Optional[str]:
        tile = cast(
            Tag,
            link.find_parent("div", {"class": lambda x: x is not None and "il_ContainerListItem" in x})
        )
        if not tile:
            return None
        description_element = cast(
            Tag,
            tile.find("div", {"class": lambda x: x is not None and "il_Description" in x})
        )
        if not description_element:
            return None
        return description_element.get_text().strip()

    @staticmethod
    def _file_to_element(name: str, url: str, link_element: Tag) -> IliasPageElement:
        # Files have a list of properties (type, modification date, size, etc.)
        # In a series of divs.
        # Find the parent containing all those divs, so we can filter our what we need
        properties_parent = cast(Tag, cast(Tag, link_element.find_parent(
            "div", {"class": lambda x: "il_ContainerListItem" in x}
        )).select_one(".il_ItemProperties"))
        # The first one is always the filetype
        file_type = cast(Tag, properties_parent.select_one("span.il_ItemProperty")).get_text().strip()

        # The rest does not have a stable order. Grab the whole text and reg-ex the date
        # out of it
        all_properties_text = properties_parent.get_text().strip()
        modification_date = IliasPage._find_date_in_text(all_properties_text)
        if modification_date is None:
            log.explain(f"Element {name} at {url} has no date.")

        # Grab the name from the link text
        full_path = name + "." + file_type

        log.explain(f"Found file {full_path!r}")
        return IliasPageElement.create_new(
            IliasElementType.FILE, url, full_path, modification_date, skip_sanitize=True
        )

    def _find_cards(self) -> list[IliasPageElement]:
        result: list[IliasPageElement] = []

        card_titles: list[Tag] = self._soup.select(".card-title a")

        for title in card_titles:
            url = self._abs_url_from_link(title)
            name = _sanitize_path_name(title.get_text().strip())
            typ = IliasPage._find_type_for_element(
                name, url, lambda: IliasPage._find_icon_from_card(title)
            )

            if not typ:
                _unexpected_html_warning()
                log.warn_contd(f"Could not extract type for {title}")
                continue

            result.append(IliasPageElement.create_new(typ, url, name))

        card_button_tiles: list[Tag] = self._soup.select(".card-title button")

        for button in card_button_tiles:
            signal_regex = re.compile("#" + str(button["id"]) + r"[\s\S]*?\.trigger\('(.+?)'")
            signal_match = signal_regex.search(str(self._soup))
            if not signal_match:
                _unexpected_html_warning()
                log.warn_contd(f"Could not find click handler signal for {button}")
                continue
            signal = signal_match.group(1)
            open_regex = re.compile(r"\.on\('" + signal + r"[\s\S]*?window.open\(['\"](.+?)['\"]")
            open_match = open_regex.search(str(self._soup))
            if not open_match:
                _unexpected_html_warning()
                log.warn_contd(f"Could not find click handler target for signal {signal} for {button}")
                continue
            url = self._abs_url_from_relative(open_match.group(1))
            name = _sanitize_path_name(button.get_text().strip())
            typ = IliasPage._find_type_for_element(
                name, url, lambda: IliasPage._find_icon_from_card(button)
            )
            caption_parent = cast(Tag, button.find_parent(
                "div",
                attrs={"class": lambda x: x is not None and "caption" in x},
            ))
            caption_container = caption_parent.find_next_sibling("div")
            if caption_container:
                description = caption_container.get_text().strip()
            else:
                description = None

            if not typ:
                _unexpected_html_warning()
                log.warn_contd(f"Could not extract type for {button}")
                continue

            result.append(IliasPageElement.create_new(typ, url, name, description=description))

        return result

    @staticmethod
    def _find_type_for_element(
        element_name: str,
        url: str,
        icon_for_element: Callable[[], Optional[Tag]],
    ) -> Optional[IliasElementType]:
        """
        Decides which sub crawler to use for a given top level element.
        """
        parsed_url = urlparse(url)
        icon = icon_for_element()

        def try_matcher(matcher: IliasElementMatcher) -> bool:
            match matcher:
                case TypeMatcher.All(matchers=ms):
                    return all(try_matcher(m) for m in ms)
                case TypeMatcher.Any(matchers=ms):
                    return any(try_matcher(m) for m in ms)
                case TypeMatcher.ImgAlt(alt=alt):
                    return icon is not None and alt in str(icon["alt"]).lower()
                case TypeMatcher.ImgSrc(src=src):
                    return icon is not None and src in str(icon["src"]).lower()
                case TypeMatcher.UrlPath(path=path):
                    return path in parsed_url.path.lower()
                case TypeMatcher.UrlParameter(query=query):
                    return query in parsed_url.query.lower()

            raise CrawlError(f"Unknown matcher {matcher}")

        for typ in IliasElementType:
            if try_matcher(typ.matcher()):
                return typ

        _unexpected_html_warning()
        log.warn_contd(f"Tried to figure out element type, but failed for {element_name!r} / {url!r})")

        if "ref_id=" in parsed_url.query.lower() or "goto.php" in parsed_url.path.lower():
            log.warn_contd("Defaulting to FOLDER as it contains a ref_id/goto")
            return IliasElementType.FOLDER

        return None

    @staticmethod
    def _find_icon_for_folder_entry(link_element: Tag) -> Optional[Tag]:
        found_parent: Optional[Tag] = None

        # We look for the outer div of our inner link, to find information around it
        # (mostly the icon)
        for parent in link_element.parents:
            if "ilContainerListItemOuter" in parent["class"] or "il-std-item" in parent["class"]:
                found_parent = parent
                break

        if found_parent is None:
            _unexpected_html_warning()
            log.warn_contd(
                f"Tried to figure out element type, but did not find an icon for {link_element!r}"
            )
            return None

        # Find the small descriptive icon to figure out the type
        img_tag: Optional[Tag] = found_parent.select_one("img.ilListItemIcon")

        if img_tag is None:
            img_tag = found_parent.select_one("img.icon")

        is_session_expansion_button = found_parent.find(
            "a",
            attrs={"href": lambda x: x is not None and ("crs_next_sess=" in x or "crs_prev_sess=" in x)}
        )
        if img_tag is None and is_session_expansion_button:
            log.explain("Found session expansion button, skipping it as it has no content")
            return None

        if img_tag is not None:
            return img_tag

        log.explain(f"Tried to figure out element type, but did not find an image for {link_element!r}")
        return None

    @staticmethod
    def _find_icon_from_card(card_title: Tag) -> Optional[Tag]:
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

        return cast(Tag, card_root.select_one(".il-card-repository-head .icon"))

    @staticmethod
    def is_logged_in(ilias_soup: IliasSoup) -> bool:
        soup = ilias_soup.soup
        # Normal ILIAS pages
        mainbar = cast(Optional[Tag], soup.find(class_="il-maincontrols-metabar"))
        if mainbar is not None:
            login_button = mainbar.find(attrs={"href": lambda x: x is not None and "login.php" in x})
            shib_login = soup.find(id="button_shib_login")
            return not login_button and not shib_login

        # Personal Desktop
        if soup.find("a", attrs={"href": lambda x: x is not None and "block_type=pditems" in x}):
            return True

        # Empty personal desktop has zero (0) markers. Match on the text...
        if alert := soup.select_one(".alert-info"):
            text = alert.get_text().lower()
            if "you have not yet selected any favourites" in text:
                return True
            if "sie haben aktuell noch keine favoriten ausgewählt" in text:
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

    @staticmethod
    def _find_date_in_text(text: str) -> Optional[datetime]:
        modification_date_match = re.search(
            r"(((\d+\. \w+ \d+)|(Gestern|Yesterday)|(Heute|Today)|(Morgen|Tomorrow)), \d+:\d+)",
            text
        )
        if modification_date_match is not None:
            modification_date_str = modification_date_match.group(1)
            return demangle_date(modification_date_str)
        return None

    def get_permalink(self) -> Optional[str]:
        return IliasPage.get_soup_permalink(self._ilias_soup)

    def _abs_url_from_link(self, link_tag: Tag) -> str:
        """
        Create an absolute url from an <a> tag.
        """
        return self._abs_url_from_relative(cast(str, link_tag.get("href")))

    def _abs_url_from_relative(self, relative_url: str) -> str:
        """
        Create an absolute url from a relative URL.
        """
        return urljoin(self._page_url, relative_url)

    @staticmethod
    def get_soup_permalink(ilias_soup: IliasSoup) -> Optional[str]:
        scripts = cast(list[Tag], ilias_soup.soup.find_all("script"))
        pattern = re.compile(r"il\.Footer\.permalink\.copyText\(\"(.+?)\"\)")
        for script in scripts:
            if match := pattern.search(script.text):
                url = match.group(1)
                url = url.replace(r"\/", "/")
                return url
        return None


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
        date_str = re.sub("Morgen|Tomorrow", _format_date_english(_tomorrow()), date_str, re.I)
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


def parse_ilias_forum_export(forum_export: BeautifulSoup) -> list[IliasForumThread]:
    elements = []
    for p in forum_export.select("body > p"):
        title_tag = p
        content_tag = cast(Optional[Tag], p.find_next_sibling("ul"))

        title = cast(Tag, p.find("b")).text
        if ":" in title:
            title = title[title.find(":") + 1:]
        title = title.strip()

        if not content_tag or content_tag.find_previous_sibling("p") != title_tag:
            # ILIAS allows users to delete the initial post while keeping the thread open
            # This produces empty threads without *any* content.
            # I am not sure why you would want this, but ILIAS makes it easy to do.
            elements.append(IliasForumThread(title, title_tag, forum_export.new_tag("ul"), None))
            continue

        mtime = _guess_timestamp_from_forum_post_content(content_tag)
        elements.append(IliasForumThread(title, title_tag, content_tag, mtime))

    return elements


def _guess_timestamp_from_forum_post_content(content: Tag) -> Optional[datetime]:
    posts = cast(Optional[Tag], content.select(".ilFrmPostHeader > span.small"))
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
