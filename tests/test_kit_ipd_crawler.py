"""
The kit-ipd crawler against a local HTTP server.
"""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Optional

import pytest
from aiohttp import BasicAuth, web

from .pferd_in_process import run_pferd

PAGE = """
<html><body>
<h1>Programmierparadigmen</h1>
<h2>Vorlesung</h2>
<p><a href="slides/01-intro.pdf">Einführung</a></p>
<h3>Zusatzmaterial</h3>
<p><a href="/material/beispiele.zip">Beispiele</a></p>
<h2>Übung</h2>
<p><a href="http://127.0.0.1:{port}/uebung/blatt1.pdf">Blatt 1</a></p>
<p><a href="uebung/Loesung.java">Lösung</a></p>
<p><a href="termine.html">Termine</a> are no file</p>
</body></html>
"""


class Server:
    def __init__(self) -> None:
        # Path -> (content, etag)
        self.files: dict[str, tuple[bytes, str]] = {
            "/course/slides/01-intro.pdf": (b"intro", '"1"'),
            "/material/beispiele.zip": (b"zip", '"2"'),
            "/uebung/blatt1.pdf": (b"blatt 1", '"3"'),
            "/course/uebung/Loesung.java": (b"class Loesung {}", '"4"'),
        }
        self.credentials: Optional[BasicAuth] = None
        self.downloads: list[str] = []
        self.port = 0

    def _authorized(self, request: web.Request) -> bool:
        if self.credentials is None:
            return True
        header = request.headers.get("Authorization")
        return header is not None and BasicAuth.decode(header) == self.credentials

    async def handle(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401, headers={"WWW-Authenticate": 'Basic realm="ipd"'})
        if request.path == "/course/":
            return web.Response(text=PAGE.format(port=self.port), content_type="text/html")
        if request.path not in self.files:
            return web.Response(status=404)
        content, etag = self.files[request.path]
        if request.method == "GET":
            self.downloads.append(request.path)
        return web.Response(body=content, headers={"ETag": etag})


RunWithServer = Callable[[Callable[[str], Awaitable[Any]]], Any]


@pytest.fixture
def server() -> Server:
    return Server()


@pytest.fixture
def with_server(server: Server) -> RunWithServer:
    """
    Calls the given function with the URL of the course page while the server runs.
    """

    def run(test: Callable[[str], Awaitable[Any]]) -> Any:
        async def main() -> Any:
            app = web.Application()
            app.router.add_route("*", "/{path:.*}", server.handle)
            runner = web.AppRunner(app)
            await runner.setup()
            # "localhost" would listen on a different port for IPv4 and IPv6
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            server.port = runner.addresses[0][1]
            try:
                return await test(f"http://127.0.0.1:{server.port}/course/")
            finally:
                await runner.cleanup()

        return asyncio.run(main())

    return run


def _files(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file() and path.name not in {".report", ".cookies"}
    }


def test_folders_from_headings(with_server: RunWithServer, tmp_path: Path) -> None:
    with_server(lambda url: run_pferd(tmp_path, {"type": "kit-ipd", "target": url}))

    # The single <h1> is the page title and no folder
    assert _files(tmp_path / "output") == {
        "Vorlesung/01-intro.pdf": b"intro",
        "Vorlesung/Zusatzmaterial/beispiele.zip": b"zip",
        "Übung/blatt1.pdf": b"blatt 1",
        "Übung/Loesung.java": b"class Loesung {}",
    }


def test_link_regex(with_server: RunWithServer, tmp_path: Path) -> None:
    crawler = {"type": "kit-ipd", "target": "", "link_regex": r"^.*\.pdf$"}

    with_server(lambda url: run_pferd(tmp_path, {**crawler, "target": url}))

    assert set(_files(tmp_path / "output")) == {"Vorlesung/01-intro.pdf", "Übung/blatt1.pdf"}


def test_etags_avoid_downloads(with_server: RunWithServer, server: Server, tmp_path: Path) -> None:
    crawler = {"type": "kit-ipd", "on_conflict": "remote-first"}
    with_server(lambda url: run_pferd(tmp_path, {**crawler, "target": url}))
    server.downloads.clear()
    server.files["/uebung/blatt1.pdf"] = (b"blatt 1 korrigiert", '"5"')

    report = with_server(lambda url: run_pferd(tmp_path, {**crawler, "target": url}))

    assert server.downloads == ["/uebung/blatt1.pdf"]
    assert report["changed"] == ["Übung/blatt1.pdf"]
    assert (tmp_path / "output/Übung/blatt1.pdf").read_bytes() == b"blatt 1 korrigiert"


def test_basic_auth(with_server: RunWithServer, server: Server, tmp_path: Path) -> None:
    server.credentials = BasicAuth("student", "secret")
    auth = {"auth:ipd": {"type": "simple", "username": "student", "password": "secret"}}

    with_server(lambda url: run_pferd(tmp_path, {"type": "kit-ipd", "target": url, "auth": "auth:ipd"}, auth))

    assert len(_files(tmp_path / "output")) == 4
