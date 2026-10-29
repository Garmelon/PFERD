import asyncio
import base64
import configparser
import json
from pathlib import Path, PurePath
from unittest.mock import AsyncMock, MagicMock

import pytest
from bs4 import BeautifulSoup

from PFERD.auth.simple import SimpleAuthenticator, SimpleAuthSection
from PFERD.config import Config
from PFERD.crawl.crawler import CrawlError
from PFERD.crawl.ilias.ilias_web_crawler import IliasWebCrawler, IliasWebCrawlerSection
from PFERD.crawl.ilias.kit_ilias_html import IliasElementType, IliasPage, IliasPageElement, IliasSoup

BASE = "https://ilias.example"
PAGE_URL = f"{BASE}/ilias.php?ref_id=1"


def page(html: str, url: str = PAGE_URL) -> IliasPage:
    return IliasPage(IliasSoup(BeautifulSoup(html, "html.parser"), url), None)


def block(title: str, content: str, block_id: str = "block") -> str:
    return f'''<div id="{block_id}" class="ilContainerBlock form-inline"
        data-store-url="./ilias.php?baseClass=ilcontainerblockpropertiesstoragegui&amp;cont_block_id=itgr_1">
      <div class="ilContainerBlockHeader"><h2 class="ilHeader ilContainerBlockHeader ">{title}</h2></div>
      <ul class="ilContainerItemsContainer">{content}</ul></div>'''


def item(title: str, href: str, file_type: str = "") -> str:
    properties = f'<div class="il_ItemProperties"><span class="il_ItemProperty">{file_type}</span></div>'
    return f'''<li class="ilCLI"><div class="ilContainerListItemOuter">
      <div class="il_ContainerListItem"><div class="il_ContainerItemTitle"><h3 class="il_ContainerItemTitle">
      <a class="il_ContainerItemTitle" href="{href}">{title}</a>
      <a class="glyph" href="#">Preview</a></h3></div>{properties}
      <a class="il_ContainerItemCommand" href="{href}">Download</a></div></div></li>'''


@pytest.fixture
def course_html() -> str:
    return f"""<html><body>
      <a href="/ilias.php?cmdClass=ilinfoscreengui">Info</a>
      <p class="ilc_Paragraph">Global description</p>
      {block("Foren", item("Discussion", "/goto.php/frm/10"), "forums")}
      {
        block(
            "Vorlesungen",
            item("Lecture 01", "/ilias.php?cmd=sendfile&amp;ref_id=11", "pdf")
            + item("Lecture 02", "/ilias.php?cmd=sendfile&amp;ref_id=12", "pdf")
            + '<p class="ilc_Paragraph">Lectures description</p>',
            "lectures",
        )
    }
      {block("Tutorien", item("Tutorial", "/goto.php/fold/13"), "tutorials")}
      {block("Ordner", item("Archives", "/goto.php/fold/14"), "folders")}
      </body></html>"""


def entries(p: IliasPage, selected: str | None = None) -> list[tuple[IliasElementType, str, str]]:
    return [(e.type, e.name, e.url) for e in p.get_child_elements(selected)]


def test_selects_original_block_and_normalizes_nested_heading(course_html: str) -> None:
    html = course_html.replace(
        '<h2 class="ilHeader ilContainerBlockHeader ">Vorlesungen</h2>',
        '<h2 class="extra ilContainerBlockHeader ilHeader trailing">  <span>Vor</span> lesungen\n  1 </h2>',
    )
    soup = BeautifulSoup(html, "html.parser")
    p = IliasPage(IliasSoup(soup, PAGE_URL), None)
    before = str(soup)
    assert p.get_container_block("  Vor  lesungen\t1 ") is soup.select_one("#lectures")
    assert str(soup) == before


@pytest.mark.parametrize("title", ["Vorles", "vorlesungen", "Vorlesungen 1", "", "  \n\t"])
def test_missing_or_blank_is_an_error_for_every_api(course_html: str, title: str) -> None:
    p = page(course_html)
    for operation in (p.get_container_block, p.get_child_elements, p.get_description):
        with pytest.raises(CrawlError):
            operation(title)


@pytest.mark.parametrize(
    "heading",
    [
        '<h2 class="ilHeader">Vorlesungen</h2>',
        '<h2 class="ilContainerBlockHeader">Vorlesungen</h2>',
        '<h3 class="ilHeader ilContainerBlockHeader">Vorlesungen</h3>',
        '<div><h2 class="ilHeader ilContainerBlockHeader">Vorlesungen</h2></div>',
    ],
)
def test_malformed_headers_do_not_match(heading: str) -> None:
    p = page(f'<div class="ilContainerBlock"><div class="ilContainerBlockHeader">{heading}</div></div>')
    with pytest.raises(CrawlError):
        p.get_container_block("Vorlesungen")


def test_duplicate_normalized_headings_are_an_error() -> None:
    p = page(block("Vorlesungen", "", "one") + block("  Vorlesungen  ", "", "two"))
    for operation in (p.get_container_block, p.get_child_elements, p.get_description):
        with pytest.raises(CrawlError):
            operation("Vorlesungen")


def test_header_must_belong_directly_to_its_container_block() -> None:
    nested_header = '<div class="ilContainerBlockHeader"><h2 class="ilHeader ilContainerBlockHeader">'
    nested_header += "Selected</h2></div>"
    p = page(block("Other", f"<div>{nested_header}</div>"))
    with pytest.raises(CrawlError):
        p.get_container_block("Selected")


def test_nested_accordion_keeps_full_virtual_folder_path() -> None:
    notes = item("Notes", "/ilias.php?cmd=sendfile&amp;ref_id=30", "pdf")
    content = f"""<div class="ilc_va_icntr_VAccordICntr">
      <div class="ilc_va_ihead_VAccordIHead"><div class="ilc_va_ihcap_VAccordIHeadCap">Week 1</div></div>
      <div class="il_VAccordionContentDef">{notes}</div>
      </div>"""
    p = page(block("Vorlesungen", content))
    assert entries(p, "Vorlesungen") == [
        (IliasElementType.FILE, "Vorlesungen/Week 1/Notes.pdf", f"{BASE}/ilias.php?cmd=sendfile&ref_id=30")
    ]


def test_description_inside_interesting_ancestor_remains_scoped() -> None:
    p = page(
        '<div class="ilCOPageSection">Outside'
        + block("Selected", '<p class="ilc_Paragraph">Inside</p>')
        + "</div>"
    )
    description = p.get_description("Selected")
    assert description is not None
    assert "Inside" in description.get_text()
    assert "Outside" not in description.get_text()


def test_scoped_entries_description_default_and_soup_reuse(course_html: str) -> None:
    soup = BeautifulSoup(course_html, "html.parser")
    p = IliasPage(IliasSoup(soup, PAGE_URL), None)
    before = str(soup)
    expected = [
        (IliasElementType.FILE, "Vorlesungen/Lecture 01.pdf", f"{BASE}/ilias.php?cmd=sendfile&ref_id=11"),
        (IliasElementType.FILE, "Vorlesungen/Lecture 02.pdf", f"{BASE}/ilias.php?cmd=sendfile&ref_id=12"),
    ]
    all_before = entries(p)
    assert entries(p, "Vorlesungen") == expected
    assert [name for _, name, _ in all_before] == [
        "Foren/Discussion",
        "Vorlesungen/Lecture 01.pdf",
        "Vorlesungen/Lecture 02.pdf",
        "Tutorien/Tutorial",
        "Ordner/Archives",
    ]
    assert entries(p, "Ordner") == [(IliasElementType.FOLDER, "Ordner/Archives", f"{BASE}/goto.php/fold/14")]
    description = p.get_description("Vorlesungen")
    assert description is not None and "Lectures description" in description.get_text()
    assert "Global description" not in description.get_text()
    assert p.get_description("Ordner") is None
    full_description = p.get_description()
    assert full_description is not None
    assert "Global description" in full_description.get_text()
    assert entries(p) == all_before
    assert str(soup) == before


def b64(value: object) -> str:
    return base64.b64encode(json.dumps(value).encode()).decode()


def h5p_init(element: str, content_id: int, title: str) -> str:
    content = b64({"library": "H5P.InteractiveVideo 1.26", "metadata": {"title": title}})
    params = b64({"interactiveVideo": {"video": {"files": [{"path": "video.webm", "mime": "video/webm"}]}}})
    return f"il.H5P.initContent('{element}', {content_id}, `{content}`, `{params}`);"


def media_content(label: str, number: int) -> str:
    return f'''<div class="il-card thumbnail"><div class="card-title">
      <a href="/goto.php/fold/{number}">{label} card</a></div></div>
      <figure class="ilc_media_cont_MediaContainer"><video><source type="video/mp4"
        src="{BASE}/video{number}.mp4"></video><figcaption>{label} MOB</figcaption></figure>
      <div class="h5p-iframe-wrapper" id="h5p{number}"><iframe class="h5p-iframe"></iframe></div>'''


def test_scopes_cards_mob_and_globally_initialized_h5p() -> None:
    integration = b64({"url": f"{BASE}/h5p"})
    html = f"""<html><head><script>var H5PIntegration = JSON.parse(atob(`{integration}`));</script></head>
      <body>{block("Selected", media_content("Inside", 21))}
      {block("Other", media_content("Outside", 22), "other")}
      <script>{h5p_init("h5p21", 21, "Inside H5P")}{h5p_init("h5p22", 22, "Outside H5P")}</script>
      </body></html>"""
    p = page(html)
    selected = entries(p, "Selected")
    assert set(selected) == {
        (IliasElementType.FOLDER, "Inside card", f"{BASE}/goto.php/fold/21"),
        (IliasElementType.MOB_VIDEO, "Inside MOB.mp4", f"{BASE}/video21.mp4"),
        (IliasElementType.H5P_VIDEO, "Selected/Inside H5P.webm", f"{BASE}/h5p/content/21/video.webm"),
    }
    assert len(entries(p)) == 6


def test_selects_dashboard_block_outside_favorites() -> None:
    favorites = '<li class="il-std-item"><div class="il-item-title">'
    favorites += '<a href="/goto.php/fold/21">Favorite</a></div></li>'
    selected = '<li class="il-std-item"><div class="il-item-title">'
    selected += '<a href="/goto.php/fold/22">Selected folder</a></div></li>'
    html = block("Favorites", favorites, "block_dash_fav_0") + block("Selected", selected, "other")
    p = page(html, f"{BASE}/ilias.php?baseClass=ilDashboardGUI&cmd=show")
    assert entries(p, "Selected") == [
        (IliasElementType.FOLDER, "Selected folder", f"{BASE}/goto.php/fold/22")
    ]
    assert entries(p) == [(IliasElementType.FOLDER, "Favorite", f"{BASE}/goto.php/fold/21")]


@pytest.mark.parametrize("playlist_exists", [True, False])
def test_scopes_mediacast_using_playlist_or_player_target(playlist_exists: bool) -> None:
    inside = '<div id="inside_player"></div>'
    if playlist_exists:
        inside += '<div id="inside_playlist"></div>'
    outside = '<div id="outside_playlist"></div><div id="outside_player"></div>'

    def init(prefix: str) -> str:
        playlist = json.dumps([{"title": prefix, "description": "", "resource": f"/{prefix}.mp4"}])
        return f"il.VideoPlaylist.init('{prefix}_playlist', '{prefix}_player', {playlist}, 'template');"

    html = block("Selected", inside) + block("Other", outside, "other")
    html += f"<script>{init('inside')}{init('outside')}</script>"
    p = page(html)
    assert entries(p, "Selected") == [(IliasElementType.MEDIACAST_VIDEO, "inside.mp4", f"{BASE}/inside.mp4")]
    assert len(entries(p)) == 2


def crawler(tmp_path: Path, title: str | None) -> IliasWebCrawler:
    config = configparser.ConfigParser()
    config["DEFAULT"] = {"working_dir": str(tmp_path)}
    config["auth:test"] = {"username": "user", "password": "password"}
    config["crawl:test"] = {
        "type": "ilias-web",
        "base_url": BASE,
        "login_type": "local",
        "client_id": "test",
        "target": "desktop",
        "output_dir": "output",
        "auth": "auth:test",
    }
    if title is not None:
        config["crawl:test"]["container_block"] = title
    auth = SimpleAuthenticator("test", SimpleAuthSection(config["auth:test"]))
    return IliasWebCrawler(
        "crawl:test", IliasWebCrawlerSection(config["crawl:test"]), Config(config), {"auth:test": auth}
    )


def token(path: str = ".") -> MagicMock:
    cl = MagicMock()
    cl.path = PurePath(path)
    cl.__aenter__ = AsyncMock()
    cl.__aexit__ = AsyncMock(return_value=False)
    return cl


def test_crawler_filters_only_final_root_page_and_not_child(tmp_path: Path, course_html: str) -> None:
    c = crawler(tmp_path, "Vorlesungen")
    landing = '<li id="tab_view_content" class=""><a href="/content">Content</a></li>'
    c._get_page = AsyncMock(
        side_effect=[
            IliasSoup(BeautifulSoup(landing, "html.parser"), PAGE_URL),
            IliasSoup(BeautifulSoup(course_html, "html.parser"), f"{BASE}/content"),
            IliasSoup(BeautifulSoup(course_html, "html.parser"), f"{BASE}/child"),
        ]
    )
    handle_element = AsyncMock(return_value=None)
    c._handle_ilias_element = handle_element
    c._download_description = AsyncMock()
    child = IliasPageElement(IliasElementType.FOLDER, f"{BASE}/child", "Child")

    async def run() -> None:
        await c._crawl_ilias_page(PAGE_URL, None, token())
        root_calls = handle_element.call_args_list.copy()
        handle_element.reset_mock()
        await c._crawl_ilias_page(child.url, child, token("Child"))
        assert [call.args[1].name for call in root_calls] == [
            "Vorlesungen/Lecture 01.pdf",
            "Vorlesungen/Lecture 02.pdf",
        ]
        assert {call.args[1].name for call in handle_element.call_args_list} == {
            "Foren/Discussion",
            "Vorlesungen/Lecture 01.pdf",
            "Vorlesungen/Lecture 02.pdf",
            "Tutorien/Tutorial",
            "Ordner/Archives",
        }

    asyncio.run(run())
    assert [call.args[0] for call in c._get_page.call_args_list] == [PAGE_URL, f"{BASE}/content", child.url]
    root_description = c._download_description.call_args_list[0].args[1].get_text()
    assert "Lectures description" in root_description and "Global description" not in root_description


def test_unfiltered_root_keeps_global_info_tab(tmp_path: Path, course_html: str) -> None:
    c = crawler(tmp_path, None)
    c._get_page = AsyncMock(return_value=IliasSoup(BeautifulSoup(course_html, "html.parser"), PAGE_URL))
    c._handle_ilias_element = AsyncMock(return_value=None)
    c._download_description = AsyncMock()
    asyncio.run(c._crawl_ilias_page(PAGE_URL, None, token()))
    found = [call.args[1] for call in c._handle_ilias_element.call_args_list]
    assert any(e.type == IliasElementType.INFO_TAB for e in found)
    assert len(found) == 6
    assert "Global description" in c._download_description.call_args.args[1].get_text()


def test_root_filter_is_applied_to_each_paginated_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = crawler(tmp_path, "Selected")
    html_pages = [
        block("Selected", item(f"Lecture {number}", f"/ilias.php?cmd=sendfile&amp;ref_id={number}", "pdf"))
        + block("Other", item("Unrelated", "/goto.php/fold/99"), "other")
        for number in (41, 42)
    ]
    c._get_page = AsyncMock(
        side_effect=[IliasSoup(BeautifulSoup(html, "html.parser"), PAGE_URL) for html in html_pages]
    )
    next_page = IliasPageElement(IliasElementType.FOLDER, f"{BASE}/next", "next")
    monkeypatch.setattr(IliasPage, "get_next_page_element", MagicMock(side_effect=[next_page, None]))
    handle_element = AsyncMock(return_value=None)
    c._handle_ilias_element = handle_element
    c._download_description = AsyncMock()
    asyncio.run(c._crawl_ilias_page(PAGE_URL, None, token()))
    assert [call.args[1].name for call in handle_element.call_args_list] == [
        "Selected/Lecture 41.pdf",
        "Selected/Lecture 42.pdf",
    ]
    assert [call.args[0] for call in c._get_page.call_args_list] == [PAGE_URL, next_page.url]


def test_missing_filter_aborts_before_cleanup_or_handlers(tmp_path: Path, course_html: str) -> None:
    c = crawler(tmp_path, "Not present")
    c._get_page = AsyncMock(return_value=IliasSoup(BeautifulSoup(course_html, "html.parser"), PAGE_URL))
    c._handle_ilias_element = AsyncMock(return_value=None)
    c._download_description = AsyncMock()
    c._output_dir.cleanup = AsyncMock()

    async def run() -> None:
        with pytest.raises(CrawlError):
            await c._crawl_ilias_page(PAGE_URL, None, token())
        await c._cleanup()

    asyncio.run(run())
    assert not c.error_free
    c._output_dir.cleanup.assert_not_awaited()
    c._handle_ilias_element.assert_not_awaited()
    c._download_description.assert_not_awaited()
