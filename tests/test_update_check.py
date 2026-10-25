import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Optional

import pytest
from aiohttp import web

from PFERD import update_check
from PFERD.update_check import Release

NOTES = "Version 99.0.0 - 2026-10-25\n\nFixed\n- Everything"


class GitHub:
    """
    The parts of the GitHub API the update check uses.
    """

    def __init__(self) -> None:
        self.tag: Optional[str] = "v99.0.0"
        self.annotated = True
        self.tags_available = True
        self.requests: list[str] = []

    async def latest_release(self, request: web.Request) -> web.Response:
        self.requests.append(request.path)
        if self.tag is None:
            return web.Response(status=403)
        return web.json_response({"tag_name": self.tag, "html_url": f"https://example.com/{self.tag}"})

    async def tag_ref(self, request: web.Request) -> web.Response:
        self.requests.append(request.path)
        if not self.tags_available:
            return web.Response(status=500)
        object_type = "tag" if self.annotated else "commit"
        return web.json_response({"object": {"type": object_type, "url": str(request.url.with_path("/tag"))}})

    async def annotated_tag(self, request: web.Request) -> web.Response:
        self.requests.append(request.path)
        return web.json_response({"message": NOTES + "\n"})


@pytest.fixture
def github() -> GitHub:
    return GitHub()


RunWithGitHub = Callable[[Callable[[str], Awaitable[Any]]], Any]


@pytest.fixture
def with_github(github: GitHub) -> RunWithGitHub:
    """
    Calls the given function with the API URL of the repository while the fake GitHub runs.
    """

    def run(test: Callable[[str], Awaitable[Any]]) -> Any:
        async def main() -> Any:
            app = web.Application()
            app.router.add_get("/repo/releases/latest", github.latest_release)
            app.router.add_get("/repo/git/ref/tags/{tag}", github.tag_ref)
            app.router.add_get("/tag", github.annotated_tag)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            try:
                return await test(f"http://127.0.0.1:{runner.addresses[0][1]}/repo")
            finally:
                await runner.cleanup()

        return asyncio.run(main())

    return run


def _write_cache(cache: Path, checked_at: float, release: Optional[Release]) -> None:
    cache.write_text(json.dumps({"checked_at": checked_at, "release": release and release.__dict__}))


YESTERDAY = time.time() - update_check.CHECK_INTERVAL_SECS - 60


def test_is_newer() -> None:
    assert update_check.is_newer("3.10.0", current="3.9.4")
    assert update_check.is_newer("3.9.4.1", current="3.9.4")
    assert not update_check.is_newer("3.9.4", current="3.9.4")
    assert not update_check.is_newer("3.9.3", current="3.9.4")
    assert not update_check.is_newer("3.10.0", current="unknown")
    assert not update_check.is_newer("3.10.0-rc1", current="3.9.4")


def test_newer_release_with_notes(with_github: RunWithGitHub, tmp_path: Path) -> None:
    release = with_github(lambda url: update_check.newest_release(url, tmp_path / "cache.json"))

    assert release == Release(version="99.0.0", url="https://example.com/v99.0.0", notes=NOTES)


def test_no_notes_for_current_release(with_github: RunWithGitHub, github: GitHub, tmp_path: Path) -> None:
    github.tag = "v0.1.0"

    release = with_github(lambda url: update_check.newest_release(url, tmp_path / "cache.json"))

    assert release == Release(version="0.1.0", url="https://example.com/v0.1.0", notes=None)
    assert github.requests == ["/repo/releases/latest"]


def test_lightweight_tag_has_no_notes(with_github: RunWithGitHub, github: GitHub, tmp_path: Path) -> None:
    github.annotated = False

    release = with_github(lambda url: update_check.newest_release(url, tmp_path / "cache.json"))

    assert release is not None and release.notes is None


def test_release_without_notes_if_tags_fail(
    with_github: RunWithGitHub, github: GitHub, tmp_path: Path
) -> None:
    github.tags_available = False

    release = with_github(lambda url: update_check.newest_release(url, tmp_path / "cache.json"))

    assert release == Release(version="99.0.0", url="https://example.com/v99.0.0", notes=None)


def test_asks_only_once_a_day(with_github: RunWithGitHub, github: GitHub, tmp_path: Path) -> None:
    cache = tmp_path / "PFERD/update-check.json"

    first = with_github(lambda url: update_check.newest_release(url, cache))
    github.tag = "v100.0.0"
    second = with_github(lambda url: update_check.newest_release(url, cache))

    assert first == second
    assert first is not None and first.notes == NOTES
    assert github.requests.count("/repo/releases/latest") == 1


def test_asks_again_after_a_day(with_github: RunWithGitHub, tmp_path: Path) -> None:
    cache = tmp_path / "update-check.json"
    _write_cache(cache, YESTERDAY, Release(version="3.9.4", url="old", notes=None))

    release = with_github(lambda url: update_check.newest_release(url, cache))

    assert release is not None and release.version == "99.0.0"


def test_failed_checks_are_remembered(with_github: RunWithGitHub, github: GitHub, tmp_path: Path) -> None:
    cache = tmp_path / "update-check.json"
    known = Release(version="98.0.0", url="known", notes="Known")
    _write_cache(cache, YESTERDAY, known)
    github.tag = None

    first = with_github(lambda url: update_check.newest_release(url, cache))
    second = with_github(lambda url: update_check.newest_release(url, cache))

    # The release we knew before is kept
    assert first == second == known
    assert github.requests == ["/repo/releases/latest"]


def test_unwritable_cache_checks_every_time(
    with_github: RunWithGitHub, github: GitHub, tmp_path: Path
) -> None:
    # A file where the cache directory should be
    (tmp_path / "PFERD").write_text("")
    cache = tmp_path / "PFERD/update-check.json"

    with_github(lambda url: update_check.newest_release(url, cache))
    release = with_github(lambda url: update_check.newest_release(url, cache))

    assert release is not None and release.version == "99.0.0"
    assert github.requests.count("/repo/releases/latest") == 2


def test_unreachable_github(tmp_path: Path) -> None:
    # Nothing listens on port 1
    release = asyncio.run(update_check.newest_release("http://127.0.0.1:1", tmp_path / "cache.json"))

    assert release is None
