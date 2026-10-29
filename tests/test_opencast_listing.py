"""
Video listings of the Opencast plugin, which is not public and can therefore not be part of the e2e tests.
The pages here only contain what the plugin renders and PFERD reads, modelled after a KIT course page.
"""

from bs4 import BeautifulSoup

from PFERD.crawl.ilias.kit_ilias_html import IliasElementType, IliasPage, IliasPageElement, IliasSoup

BASE_URL = "https://ilias.example.com"
LISTING_URL = (
    f"{BASE_URL}/ilias.php?baseClass=ilobjplugindispatchgui&cmdClass=xoctEventGUI&ref_id=1&page_size=10"
)


def _card(title: str, url: str) -> str:
    return f"""
        <section class="c-entity__container">
          <div class="c-entity__primary-identifier"><a href="{url}" target="_blank">{title}</a></div>
          <div class="c-entity__secondary-identifier --image">
            <a href="{url}"><img alt="Preview of Video: {title}" src="{BASE_URL}/preview.jpg"></a>
          </div>
          <div class="c-entity__main-details"><dl><dt>Datum</dt><dd>26. Oct 2026, 12:56</dd></dl></div>
        </section>
    """


def _listing(*cards: str) -> list[IliasPageElement]:
    header_image = "./Customizing/global/plugins/Services/Repository/RepositoryObject/OpenCast/icon_xoct.svg"
    html = f"""
        <html><body>
        <img id="headerimage" src="{header_image}">
        {"".join(cards)}
        </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    element = IliasPageElement.create_new(IliasElementType.OPENCAST_VIDEO_FOLDER, LISTING_URL, "Recordings")
    return IliasPage(IliasSoup(soup, LISTING_URL), element).get_child_elements()


def test_player_links_are_found_once() -> None:
    player = f"{BASE_URL}/ilias.php?baseClass=ilobjplugindispatchgui&cmdClass=xoctPlayerGUI&cmd=streamVideo"
    elements = _listing(
        _card("Chapter 00 Part 1", f"{player}&eid=a"), _card("Chapter 01 Part 1", f"{player}&eid=b")
    )

    assert [(e.name, e.type, e.url) for e in elements] == [
        ("Chapter 00 Part 1.mp4", IliasElementType.OPENCAST_VIDEO_PLAYER, f"{player}&eid=a"),
        ("Chapter 01 Part 1.mp4", IliasElementType.OPENCAST_VIDEO_PLAYER, f"{player}&eid=b"),
    ]


def test_media_library_links_are_found_once() -> None:
    url = "https://ilias-medien.bibliothek.kit.edu/details/a"
    elements = _listing(_card("Chapter 00 Part 1", url))

    assert [(e.name, e.type, e.url) for e in elements] == [
        ("Chapter 00 Part 1.mp4", IliasElementType.KIT_MEDIA_PORTAL_VIDEO_PLAYER, url),
    ]
