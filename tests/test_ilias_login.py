import asyncio
import configparser
from pathlib import Path, PurePath
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from PFERD.auth import Authenticator, AuthError
from PFERD.auth.simple import SimpleAuthenticator, SimpleAuthSection
from PFERD.config import Config
from PFERD.crawl.crawler import CrawlError
from PFERD.crawl.ilias.ilias_web_crawler import IliasWebCrawler, IliasWebCrawlerSection
from PFERD.crawl.ilias.kit_ilias_html import IliasElementType, IliasPageElement

LOGIN_FORM = '<form name="login_form" action="submit.php?attempt={attempt}"></form>'
LOGGED_IN = '<div class="il-maincontrols-metabar"></div>'


class RetryAuthenticator(Authenticator):
    def __init__(self) -> None:
        super().__init__("test")
        self.invalidations = 0

    async def credentials(self) -> tuple[str, str]:
        return "user", "correct" if self.invalidations else "wrong"

    def invalidate_credentials(self) -> None:
        self.invalidations += 1


def crawler(
    tmp_path: Path, auth: Authenticator, base_url: str = "https://ilias.example", **options: str
) -> IliasWebCrawler:
    parser = configparser.ConfigParser()
    parser["DEFAULT"] = {"working_dir": str(tmp_path)}
    parser["crawl:test"] = {
        **options,
        "type": "ilias-web",
        "base_url": base_url,
        "login_type": "local",
        "client_id": "test",
        "target": "desktop",
        "output_dir": "output",
        "auth": "auth:test",
    }
    return IliasWebCrawler(
        "crawl:test", IliasWebCrawlerSection(parser["crawl:test"]), Config(parser), {"auth:test": auth}
    )


def response(html: str) -> MagicMock:
    result = MagicMock()
    result.url = "https://ilias.example/submit.php"
    result.read = AsyncMock(return_value=html.encode())
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=result)
    return context


def test_local_login_retries_with_fresh_form(tmp_path: Path) -> None:
    auth = RetryAuthenticator()
    instance = crawler(tmp_path, auth)
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.side_effect = [response(LOGIN_FORM.format(attempt=i)) for i in (1, 2)]
    session.post.side_effect = [response(LOGIN_FORM.format(attempt=1)), response(LOGGED_IN)]
    instance.session = session

    asyncio.run(instance._authenticate())

    assert auth.invalidations == 1
    assert session.get.call_count == 2
    assert [call.args[0] for call in session.post.call_args_list] == [
        "https://ilias.example/submit.php?attempt=1",
        "https://ilias.example/submit.php?attempt=2",
    ]
    # Inspect the actual submitted credentials, rather than just the number of attempts.
    assert [
        {field[0]["name"]: field[2] for field in call.kwargs["data"]._fields}
        for call in session.post.call_args_list
    ] == [
        {"login_form/input_3/input_4": "user", "login_form/input_3/input_5": "wrong"},
        {"login_form/input_3/input_4": "user", "login_form/input_3/input_5": "correct"},
    ]


def test_local_login_rejects_invalid_configured_credentials(tmp_path: Path) -> None:
    parser = configparser.ConfigParser()
    parser["auth:test"] = {"username": "user", "password": "wrong"}
    auth = SimpleAuthenticator("test", SimpleAuthSection(parser["auth:test"]))
    instance = crawler(tmp_path, auth)
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.return_value = response(LOGIN_FORM.format(attempt=1))
    session.post.return_value = response(LOGIN_FORM.format(attempt=1))
    instance.session = session

    with pytest.raises(AuthError, match="Configured credentials are invalid"):
        asyncio.run(instance._authenticate())

    assert session.get.call_count == 1
    assert session.post.call_count == 1


@pytest.mark.parametrize("html", ["<html></html>", '<form name="login_form"></form>'])
def test_local_login_rejects_invalid_form(tmp_path: Path, html: str) -> None:
    auth = RetryAuthenticator()
    instance = crawler(tmp_path, auth)
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.return_value = response(html)
    instance.session = session

    with pytest.raises(CrawlError, match="Could not find"):
        asyncio.run(instance._authenticate())

    assert auth.invalidations == 0
    session.post.assert_not_called()


@pytest.mark.parametrize("base_url", ["https://ilias.example/ilias", "https://ilias.example/ilias/"])
def test_local_login_respects_base_url_path(tmp_path: Path, base_url: str) -> None:
    auth = RetryAuthenticator()
    auth.invalidations = 1  # Return the correct password on the first attempt
    instance = crawler(tmp_path, auth, base_url=base_url)
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.return_value = response(LOGIN_FORM.format(attempt=1))
    session.post.return_value = response(LOGGED_IN)
    instance.session = session

    asyncio.run(instance._authenticate())

    assert session.get.call_args.args[0] == "https://ilias.example/ilias/login.php"
    assert session.post.call_args.args[0] == "https://ilias.example/ilias/submit.php?attempt=1"


def test_ignored_links_are_not_resolved(tmp_path: Path) -> None:
    instance = crawler(tmp_path, RetryAuthenticator(), links="ignore")
    instance.session = MagicMock(spec=aiohttp.ClientSession)
    element = IliasPageElement(IliasElementType.LINK, "https://ilias.example/goto.php/webr/1", "Link")

    assert asyncio.run(instance._handle_link(element, PurePath("Link"))) is None
    instance.session.get.assert_not_called()
