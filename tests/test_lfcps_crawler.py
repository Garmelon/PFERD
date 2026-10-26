"""
The lfcps crawler against a local HTTP server.
"""

import asyncio
from pathlib import Path
from typing import Any

from aiohttp import web

from .pferd_in_process import run_pferd

PAGE = """
<html><body>
<a href="lfcps-syllabus.pdf">Syllabus</a>
<a href="../lfcps/lfcps-slides.zip">All slides</a>
<h4 id="course-schedule">Schedule</h4>
<table>
<tr><td><a href="https://doi.org/10.1007/1">Intro</a></td>
<td>(<a title="slides" href="../lfcps/slide/01-intro-slides.pdf">⊞</a>)</td></tr>
<tr><td><a href="https://doi.org/10.1007/2">Loops</a></td>
<td>(<a title="slides" href="/lfcps/slide/02-loops-slides.pdf">⊞</a>)
(<a title="code" href="/lfcps/code/02-loops.kyx">K</a>)</td></tr>
<tr><td class="recitation">Ü: <a href="Ex1.pdf">Modeling</a></td>
<td>(<a title="code" href="Ex1.kyx">K</a>)</td></tr>
<tr><td class="recitation">Ü: <a href="Ex2.pdf">Missing</a></td></tr>
<tr><td>(<a title="slides" href="../lfcps/slide/01-intro-slides.pdf">⊞</a>)</td></tr>
</table>
<table><tr><td><a href="../lfcps/lfcps-slides.zip">Book slides</a></td></tr></table>
</body></html>
"""

FILES = {
    "/course/lfcps-syllabus.pdf": b"syllabus",
    "/lfcps/lfcps-slides.zip": b"all slides",
    "/lfcps/slide/01-intro-slides.pdf": b"intro",
    "/lfcps/slide/02-loops-slides.pdf": b"loops",
    "/lfcps/code/02-loops.kyx": b"loops code",
    "/course/Ex1.pdf": b"ex 1",
    "/course/Ex1.kyx": b"ex 1 code",
}


def _crawl(tmp_path: Path) -> dict[str, Any]:
    async def handle(request: web.Request) -> web.Response:
        if request.path == "/course/lfcps-schedule.html":
            return web.Response(text=PAGE, content_type="text/html")
        if request.path not in FILES:
            return web.Response(status=404)
        return web.Response(body=FILES[request.path])

    async def main() -> dict[str, Any]:
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        try:
            target = f"http://127.0.0.1:{port}/course/lfcps-schedule.html"
            return await run_pferd(tmp_path, {"type": "lfcps", "target": target})
        finally:
            await runner.cleanup()

    return asyncio.run(main())


def _files(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file() and path.name not in {".report", ".cookies"}
    }


def test_sorts_schedule_files(tmp_path: Path) -> None:
    _crawl(tmp_path)

    # Files outside the schedule table that are not next to the page are skipped
    assert _files(tmp_path / "output") == {
        "lfcps-syllabus.pdf": b"syllabus",
        "Slides/01-intro-slides.pdf": b"intro",
        "Slides/02-loops-slides.pdf": b"loops",
        "Code/02-loops.kyx": b"loops code",
        "Exercises/Ex1.pdf": b"ex 1",
        "Exercises/Ex1.kyx": b"ex 1 code",
    }


def test_dead_link_is_warning(tmp_path: Path) -> None:
    report = _crawl(tmp_path)

    assert report["encountered_errors"] == []
    assert len(report["encountered_warnings"]) == 1
    assert "Ex2.pdf" in report["encountered_warnings"][0]
