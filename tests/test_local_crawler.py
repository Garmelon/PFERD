import asyncio
import os
from pathlib import Path

from .pferd_in_process import run_pferd


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _files(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): path.read_text()
        for path in directory.rglob("*")
        if path.is_file() and path.name != ".report"
    }


def test_copies_tree(tmp_path: Path) -> None:
    _write(tmp_path / "source/top.txt", "top\n")
    _write(tmp_path / "source/a/b/deep.txt", "deep\n")

    report = asyncio.run(run_pferd(tmp_path, {"type": "local", "target": "source"}))

    assert _files(tmp_path / "output") == {"top.txt": "top\n", "a/b/deep.txt": "deep\n"}
    assert sorted(report["added"]) == ["a/b/deep.txt", "top.txt"]


def test_second_run_updates_changes(tmp_path: Path) -> None:
    crawler = {"type": "local", "target": "source", "on_conflict": "remote-first"}
    _write(tmp_path / "source/unchanged.txt", "unchanged\n")
    _write(tmp_path / "source/changed.txt", "old\n")
    _write(tmp_path / "source/deleted.txt", "deleted\n")
    asyncio.run(run_pferd(tmp_path, crawler))

    _write(tmp_path / "source/changed.txt", "new\n")
    # Newer than the copy, which has the modification time of the old version
    later = (tmp_path / "output/changed.txt").stat().st_mtime + 60
    os.utime(tmp_path / "source/changed.txt", (later, later))
    (tmp_path / "source/deleted.txt").unlink()
    _write(tmp_path / "source/added.txt", "added\n")
    report = asyncio.run(run_pferd(tmp_path, crawler))

    assert _files(tmp_path / "output") == {
        "unchanged.txt": "unchanged\n",
        "changed.txt": "new\n",
        "added.txt": "added\n",
    }
    assert report["added"] == ["added.txt"]
    assert report["changed"] == ["changed.txt"]
    assert report["deleted"] == ["deleted.txt"]


def test_transform(tmp_path: Path) -> None:
    _write(tmp_path / "source/keep.txt", "keep\n")
    _write(tmp_path / "source/skip/file.txt", "skip\n")
    crawler = {"type": "local", "target": "source", "transform": "skip --> !\n  keep.txt --> renamed.txt"}

    asyncio.run(run_pferd(tmp_path, crawler))

    assert _files(tmp_path / "output") == {"renamed.txt": "keep\n"}
