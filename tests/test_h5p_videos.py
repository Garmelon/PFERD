"""
Interactive videos of the H5P plugin, which is not public and can therefore not be part of the e2e tests.
The pages here only contain what the plugin renders and PFERD reads, modelled after a KIT course page.
"""

import base64
import json
from typing import Any

from bs4 import BeautifulSoup

from PFERD.crawl.ilias.ilias_web_crawler import _VIDEO_ELEMENTS
from PFERD.crawl.ilias.kit_ilias_html import IliasElementType, IliasPage, IliasPageElement, IliasSoup

BASE_URL = "https://ilias.example.com"
CONTENT_URL = f"{BASE_URL}/data/client/h5p"


def _b64(value: Any) -> str:
    return base64.b64encode(json.dumps(value).encode()).decode()


def _init_content(
    element_id: str, content_id: int, library: str, title: str, files: list[dict[str, str]]
) -> str:
    content = {"library": library, "title": "short-title", "metadata": {"title": title}}
    parameters = {"interactiveVideo": {"video": {"files": files}}}
    return f"""
        try {{ il.H5P.initContent(
            '{element_id}',
            {content_id},
            `{_b64(content)}`,
            `{_b64(parameters)}`,
            `{_b64({})}`,
        ); }} catch (e) {{ console.log(e); }}
    """


def _page(*init_contents: str) -> list[IliasPageElement]:
    integration = f"var H5PIntegration = JSON.parse(atob(`{_b64({'url': CONTENT_URL})}`));"
    integration_src = "data:application/javascript;base64," + base64.b64encode(integration.encode()).decode()
    # Every content is initialized twice by the plugin
    scripts = "".join(init_contents) * 2
    html = f"""
        <html><head><script src="{integration_src}"></script></head><body>
        <div class="ilc_va_icntr_VAccordICntr">
          <div class="ilc_va_ihead_VAccordIHead"><div class="ilc_va_ihcap_VAccordIHeadCap">Woche 1</div></div>
          <div class="il_VAccordionContentDef">
            <div class="h5p-iframe-wrapper" id="in_accordion"><iframe class="h5p-iframe"></iframe></div>
          </div>
        </div>
        <div class="h5p-iframe-wrapper" id="top_level"><iframe class="h5p-iframe"></iframe></div>
        <script>{scripts}</script>
        </body></html>
    """
    soup = BeautifulSoup(html, "html.parser")
    page = IliasPage(IliasSoup(soup, f"{BASE_URL}/ilias.php?baseClass=ilrepositorygui&ref_id=1"), None)
    return [element for element in page.get_child_elements() if element.type == IliasElementType.H5P_VIDEO]


WEBM = {"path": "videos/files-1.webm", "mime": "video/webm"}
MP4 = {"path": "videos/files-1.mp4", "mime": "video/mp4"}


def test_prefers_webm_and_uses_title() -> None:
    [video] = _page(_init_content("top_level", 42, "H5P.InteractiveVideo 1.26", "Video: Intro", [MP4, WEBM]))

    assert video.name == "Video: Intro.webm"
    assert video.url == f"{CONTENT_URL}/content/42/videos/files-1.webm"
    assert video.id() == "42"


def test_uses_other_format_without_webm() -> None:
    [video] = _page(_init_content("top_level", 42, "H5P.InteractiveVideo 1.22", "Video: Intro", [MP4]))

    assert video.name == "Video: Intro.mp4"
    assert video.url == f"{CONTENT_URL}/content/42/videos/files-1.mp4"


def test_video_in_accordion_is_in_its_folder() -> None:
    [video] = _page(_init_content("in_accordion", 42, "H5P.InteractiveVideo 1.26", "Video: Intro", [WEBM]))

    assert video.name == "Woche 1/Video: Intro.webm"


def test_title_is_sanitized() -> None:
    [video] = _page(_init_content("top_level", 42, "H5P.InteractiveVideo 1.26", "Ideal/Real", [WEBM]))

    assert video.name == "Ideal-Real.webm"


def test_ignores_other_content_and_external_videos() -> None:
    external = {"path": "https://www.youtube.com/watch?v=abc", "mime": "video/YouTube"}
    videos = _page(
        _init_content("top_level", 1, "H5P.MultiChoice 1.16", "Quiz", []),
        _init_content("top_level", 2, "H5P.InteractiveVideo 1.26", "YouTube", [external]),
        _init_content("top_level", 3, "H5P.InteractiveVideo 1.26", "Own", [WEBM]),
    )

    assert [video.name for video in videos] == ["Own.webm"]


def test_counts_as_video() -> None:
    # Only downloaded with the "videos" option
    assert IliasElementType.H5P_VIDEO in _VIDEO_ELEMENTS
