from enum import Enum
from typing import Optional, cast

import bs4

from PFERD.utils import soupify

_link_template_plain = "{{link}}"
_link_template_fancy = """
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
""".strip()  # noqa: E501 line too long

_link_template_internet_shortcut = """
[InternetShortcut]
URL={{link}}
""".strip()

_learning_module_template = """
<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>{{name}}</title>
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
    .nav {
        display: flex;
        justify-content: space-between;
    }
    </style>
    <body class="center-flex">
{{body}}
    </body>
</html>
"""

_forum_thread_template = """
<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>ILIAS - Forum: {{name}}</title>
        <style>
            * {
                box-sizing: border-box;
            }
            body {
                font-family: 'Open Sans', Verdana, Arial, Helvetica, sans-serif;
                padding: 8px;
            }
            ul, ol, p {
                margin: 1.2em 0;
            }
            p {
                margin-top: 8px;
                margin-bottom: 8px;
            }
            a {
                color: #00876c;
                text-decoration: none;
                cursor: pointer;
            }
            a:hover {
                text-decoration: underline;
            }
            body > p:first-child > span:first-child {
                font-size: 1.6em;
            }
            body > p:first-child > span:first-child ~ span.default {
                display: inline-block;
                font-size: 1.2em;
                padding-bottom: 8px;
            }
            .ilFrmPostContent {
                margin-top: 8px;
                max-width: 64em;
            }
            .ilFrmPostContent > *:first-child {
                margin-top: 0px;
            }
            .ilFrmPostTitle {
                margin-top: 24px;
                color: #00876c;
                font-weight: bold;
            }
            #ilFrmPostList {
                list-style: none;
                padding-left: 0;
            }
            li.ilFrmPostRow {
                padding: 3px 0 3px 3px;
                margin-bottom: 24px;
                border-left: 6px solid #dddddd;
            }
            .ilFrmPostRow > div {
                display: flex;
            }
            .ilFrmPostImage img {
                margin: 0 !important;
                padding: 6px 9px 9px 6px;
            }
            .ilUserIcon {
                width: 115px;
            }
            .small {
                text-decoration: none;
                font-size: 0.75rem;
                color: #6f6f6f;
            }
        </style>
    </head>
    <body>
    {{heading}}
    {{content}}
    </body>
</html>
""".strip()  # noqa: E501 line too long


def learning_module_template(body: bs4.Tag, name: str, prev: Optional[str], next: Optional[str]) -> str:
    # Seems to be comments, ignore those.
    for elem in body.select(".il-copg-mob-fullscreen-modal"):
        elem.decompose()

    nav_template = """
        <div class="nav">
            {{left}}
            {{right}}
        </div>
    """
    if prev and body.select_one(".ilc_page_lnav_LeftNavigation"):
        text = cast(bs4.Tag, body.select_one(".ilc_page_lnav_LeftNavigation")).get_text().strip()
        left = f'<a href="{prev}">{text}</a>'
    else:
        left = "<span></span>"

    if next and body.select_one(".ilc_page_rnav_RightNavigation"):
        text = cast(bs4.Tag, body.select_one(".ilc_page_rnav_RightNavigation")).get_text().strip()
        right = f'<a href="{next}">{text}</a>'
    else:
        right = "<span></span>"

    if top_nav := body.select_one(".ilc_page_tnav_TopNavigation"):
        top_nav.replace_with(
            soupify(nav_template.replace("{{left}}", left).replace("{{right}}", right).encode())
        )

    if bot_nav := body.select_one(".ilc_page_bnav_BottomNavigation"):
        bot_nav.replace_with(soupify(nav_template.replace(
            "{{left}}", left).replace("{{right}}", right).encode())
        )

    body_str = cast(str, body.prettify())
    return _learning_module_template.replace("{{body}}", body_str).replace("{{name}}", name)


def forum_thread_template(name: str, url: str, heading: bs4.Tag, content: bs4.Tag) -> str:
    if title := cast(Optional[bs4.Tag], heading.find(name="b")):
        title.wrap(bs4.Tag(name="a", attrs={"href": url}))
    return _forum_thread_template \
        .replace("{{name}}", name) \
        .replace("{{heading}}", cast(str, heading.prettify())) \
        .replace("{{content}}", cast(str, content.prettify()))


class Links(Enum):
    IGNORE = "ignore"
    PLAINTEXT = "plaintext"
    FANCY = "fancy"
    INTERNET_SHORTCUT = "internet-shortcut"

    def template(self) -> Optional[str]:
        if self == Links.FANCY:
            return _link_template_fancy
        elif self == Links.PLAINTEXT:
            return _link_template_plain
        elif self == Links.INTERNET_SHORTCUT:
            return _link_template_internet_shortcut
        elif self == Links.IGNORE:
            return None
        raise ValueError("Missing switch case")

    def extension(self) -> Optional[str]:
        if self == Links.FANCY:
            return ".html"
        elif self == Links.PLAINTEXT:
            return ".txt"
        elif self == Links.INTERNET_SHORTCUT:
            return ".url"
        elif self == Links.IGNORE:
            return None
        raise ValueError("Missing switch case")

    @staticmethod
    def from_string(string: str) -> "Links":
        try:
            return Links(string)
        except ValueError:
            raise ValueError("must be one of 'ignore', 'plaintext',"
                             " 'html', 'internet-shortcut'")
