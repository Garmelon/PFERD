import configparser
import io

import pytest

from PFERD.cli import PARSER
from PFERD.crawl.ilias.ilias_web_crawler import IliasWebCrawlerSection


@pytest.mark.parametrize("command", ["ilias-web", "kit-ilias-web"])
@pytest.mark.parametrize("title", [None, "", "Vorlesungen", "  Week  1  "])
def test_container_block_cli_serializes_for_both_commands(command: str, title: str | None) -> None:
    argv = [command, "123", "output"]
    if title is not None:
        argv += ["--container-block", title]
    args = PARSER.parse_args(argv)
    config = configparser.ConfigParser()
    args.command(args, config)
    section = config["crawl:ilias"]
    assert section.get("container_block") == title
    assert IliasWebCrawlerSection(section).container_block() == title
    if title is None:
        assert "container_block" not in section

    # Check that the generated setting also survives writing and re-reading an INI file.
    serialized = io.StringIO()
    config.write(serialized)
    reloaded = configparser.ConfigParser()
    reloaded.read_string(serialized.getvalue())
    assert IliasWebCrawlerSection(reloaded["crawl:ilias"]).container_block() == (
        title.strip() if title is not None else None
    )


def test_section_reads_optional_config_without_cli() -> None:
    config = configparser.ConfigParser()
    config.read_string("[crawl:test]\ntype = ilias-web\ncontainer_block = Tutorien\n")
    assert IliasWebCrawlerSection(config["crawl:test"]).container_block() == "Tutorien"
    del config["crawl:test"]["container_block"]
    assert IliasWebCrawlerSection(config["crawl:test"]).container_block() is None
