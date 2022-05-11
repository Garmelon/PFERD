from bs4 import BeautifulSoup, Comment, Tag

_STYLE_TAG_CONTENT = """
    .ilc_text_block_Information {
      background-color: #f5f7fa;
    }
    div.ilc_text_block_Standard {
      margin-bottom: 10px;
      margin-top: 10px;
    }
    span.ilc_text_inline_Strong {
      font-weight: bold;
    }

    .accordion-head {
      background-color: #f5f7fa;
      padding: 0.5rem 0;
    }

    h3 {
      margin-top: 0.5rem;
      margin-bottom: 1rem;
    }

    br.visible-break {
      margin-bottom: 1rem;
    }

    article {
      margin: 0.5rem 0;
    }

    body {
      padding: 1em;
      grid-template-columns: 1fr min(60rem, 90%) 1fr;
      line-height: 1.2;
    }
"""

_ARTICLE_WORTHY_CLASSES = [
    "ilc_text_block_Information",
    "ilc_section_Attention",
    "ilc_section_Link",
]


def insert_base_markup(soup: BeautifulSoup) -> BeautifulSoup:
    head = soup.new_tag("head")
    soup.insert(0, head)

    simplecss_link: Tag = soup.new_tag("link")
    # <link rel="stylesheet" href="https://cdn.simplecss.org/simple.css">
    simplecss_link["rel"] = "stylesheet"
    simplecss_link["href"] = "https://cdn.simplecss.org/simple.css"
    head.append(simplecss_link)

    # Basic style tags for compat
    style: Tag = soup.new_tag("style")
    style.append(_STYLE_TAG_CONTENT)
    head.append(style)

    return soup


def clean(soup: BeautifulSoup) -> BeautifulSoup:
    for block in soup.find_all(class_=lambda x: x in _ARTICLE_WORTHY_CLASSES):
        block.name = "article"

    for block in soup.find_all("h3"):
        block.name = "div"

    for block in soup.find_all("h1"):
        block.name = "h3"

    for block in soup.find_all(class_="ilc_va_ihcap_VAccordIHeadCap"):
        block.name = "h3"
        block["class"] += ["accordion-head"]

    for dummy in soup.select(".ilc_text_block_Standard.ilc_Paragraph"):
        children = list(dummy.children)
        if not children:
            dummy.decompose()
        if len(children) > 1:
            continue
        if type(children[0]) == Comment:
            dummy.decompose()

    for hrule_imposter in soup.find_all(class_="ilc_section_Separator"):
        hrule_imposter.insert(0, soup.new_tag("hr"))

    return soup
