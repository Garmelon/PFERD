"""
Explicit checks for behaviour the snapshots of test_courses.py do not describe well.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from .conftest import Ilias, RunPferd
from .manifest import manifest

# The default timezone of ILIAS, in which it shows all dates
ILIAS_TIMEZONE = ZoneInfo("Europe/Berlin")


@pytest.mark.parametrize(
    ("course", "dates"),
    [
        ("dates", "file_dates"),
        # Dates like "9. Dez 2024, 14:00" inside accordions and next to other properties
        ("kit_lecture", "kit_lecture_file_dates"),
    ],
)
def test_file_dates_become_mtimes(
    course: str, dates: str, student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path
) -> None:
    run = run_pferd(ilias.course(course), tmp_path, user=student)

    for path, timestamp in ilias.seed[dates].items():
        # ILIAS shows the date in its timezone with minute precision and PFERD interprets it as local time
        expected = datetime.fromtimestamp(timestamp, ILIAS_TIMEZONE).replace(tzinfo=None, second=0)
        actual = datetime.fromtimestamp((run.output / path).stat().st_mtime)
        assert actual == expected, path


def test_unsupported_elements_are_ignored(
    student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path
) -> None:
    run = run_pferd(ilias.course("unsupported"), tmp_path, user=student)
    log = re.sub(r"\s+", " ", run.log)

    for title, reason in [
        ("Online Test", "tests contain no relevant data"),
        ("Survey", "surveys contain no relevant data"),
        ("SCORM Module", "scorm learning modules are not supported"),
        ("Literature List", "literature lists are not currently supported"),
        ("HTML Module", "HTML learning modules are not supported"),
        ("Blog", "blogs are not currently supported"),
        ("Data Collection", "dcl record lists are not currently supported"),
        ("Media Pool", "media pools are not currently supported"),
        ("Wiki", "wikis are not currently supported"),
        ("Individual Assessment", "individual assessments are not currently supported"),
        # Course references show the title of the referenced course
        ("Structure", "not descending into linked course"),
    ]:
        assert f"Ignored '{title}' ({reason})" in log
    assert set(manifest(run.output, ilias.base_url)) == {"supported.txt"}


def test_unavailable_elements_are_skipped(
    student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path
) -> None:
    run = run_pferd(ilias.course("availability"), tmp_path, user=student)

    assert set(manifest(run.output, ilias.base_url)) == {"available.txt"}


def test_learning_module_pages(student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path) -> None:
    run = run_pferd(ilias.course("learning_module"), tmp_path, user=student)

    assert set(manifest(run.output, ilias.base_url)) == {
        "Lecture Notes/00_Introduction.html",
        "Lecture Notes/01_Basics.html",
        "Lecture Notes/02_Advanced Topics.html",
        "Recordings/00_Lecture 1.html",
    }
    # Each page links to its neighbours, at the top and the bottom
    links = re.findall(r'<a href="([^"]+\.html)">', (run.output / "Lecture Notes/01_Basics.html").read_text())
    assert sorted(links) == ["00_Introduction.html"] * 2 + ["02_Advanced Topics.html"] * 2


def test_content_page_file_names(student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path) -> None:
    run = run_pferd(ilias.course("content_page"), tmp_path, user=student)

    assert set(manifest(run.output, ilias.base_url)) == {"Material/small.pdf", "Material/large.pdf"}


def test_nested_accordions(student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path) -> None:
    run = run_pferd(ilias.course("nesting"), tmp_path, user=student)

    assert "Outer/Inner/Inner Group/inner.txt" in manifest(run.output, ilias.base_url)


# Item groups without a title have a screen reader only heading "Leerer Titel" / "Empty title"
@pytest.mark.parametrize(
    ("course", "path"),
    [
        ("kit_collapsed_groups", "untitled.pdf"),
        # Inside an accordion, as KIT lectures put a week's files into untitled item groups
        ("kit_weekly_accordions", "Woche 1: Einführung und Commitment-Protokolle/vl-0-prolog-01-intro.pdf"),
    ],
)
def test_untitled_item_group_has_no_folder(
    course: str, path: str, student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path
) -> None:
    run = run_pferd(ilias.course(course), tmp_path, user=student)

    assert path in manifest(run.output, ilias.base_url)


def test_inaccessible_group_is_skipped(
    student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path
) -> None:
    # The students see the tutorial groups they are not a member of, but can not open them
    run = run_pferd(ilias.course("kit_lecture"), tmp_path, user=student)

    assert run.warnings == [], run.log
    groups = {
        path.split("/")[1] for path in manifest(run.output, ilias.base_url) if path.startswith("Gruppen/")
    }
    assert groups == {"Tutorium 01 Mittwoch Block 2 (20.22 Raum 123)"}


def test_plaintext_link_contains_url(student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path) -> None:
    run = run_pferd(ilias.course("links"), tmp_path, user=student, options={"links": "plaintext"})

    assert (run.output / "KIT Homepage.txt").read_text().strip() == "https://www.kit.edu"
    assert (run.output / "Useful Links" / "Python.txt").read_text().strip() == "https://www.python.org"


# The files of the course created by changes.php, before it is changed
FIRST_RUN_FILES = {"unchanged.txt", "changed.txt", "deleted.txt", "Deleted Folder/in-folder.txt"}


@pytest.mark.parametrize("on_conflict", ["remote-first", "no-delete", "local-first"])
def test_changes_between_runs(
    on_conflict: str, student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path
) -> None:
    options = {"on_conflict": on_conflict}
    refs = ilias.run_php("changes.php", "create")
    first = run_pferd(refs["course"], tmp_path, user=student, options=options)
    assert set(manifest(first.output, ilias.base_url)) == FIRST_RUN_FILES

    ilias.run_php("changes.php", "change", json.dumps(refs))
    second = run_pferd(refs["course"], tmp_path, user=student, options=options)

    assert second.errors == [], second.log
    assert second.report["added"] == ["added.txt"]
    files = set(manifest(second.output, ilias.base_url))
    changed_content = (second.output / "changed.txt").read_text()

    if on_conflict == "remote-first":
        assert second.report["changed"] == ["changed.txt"]
        assert sorted(second.report["deleted"]) == ["Deleted Folder/in-folder.txt", "deleted.txt"]
        assert files == {"unchanged.txt", "changed.txt", "added.txt"}
        assert changed_content == "New content\n"
    elif on_conflict == "no-delete":
        assert second.report["changed"] == ["changed.txt"]
        assert second.report["deleted"] == []
        # The not deleted folder is reported, not the files in it
        assert sorted(second.report["not_deleted"]) == ["Deleted Folder", "deleted.txt"]
        assert files == {*FIRST_RUN_FILES, "added.txt"}
        assert changed_content == "New content\n"
    else:
        assert second.report["changed"] == []
        assert second.report["deleted"] == []
        assert files == {*FIRST_RUN_FILES, "added.txt"}
        assert changed_content == "Content of changed.txt\n"


def test_session_is_reused(student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path) -> None:
    course = ilias.course("structure")
    run_pferd(course, tmp_path, user=student)

    # The saved session needs no login, so the password does not matter
    reused = run_pferd(course, tmp_path, user=student, password="wrong")
    assert reused.errors == [], reused.log

    # An expired session needs a new login
    cookies = tmp_path / "course" / ".cookies"
    cookies.write_text(re.sub(r"PHPSESSID=[^;]+", "PHPSESSID=expired", cookies.read_text()))
    run_pferd(course, tmp_path, user=student, password="wrong", expected_exit_code=1)
    relogin = run_pferd(course, tmp_path, user=student)
    assert relogin.errors == [], relogin.log
    assert "top.txt" in manifest(relogin.output, ilias.base_url)


def test_transform(student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path) -> None:
    rules = [
        '"Folder A/Nested B" --> !',
        '"Group G" -name-> Gruppe',
        r"(.*)\.txt -re-> {g1.upper()}.text",
    ]
    # Continuation lines of a config value are indented
    run = run_pferd(
        ilias.course("structure"), tmp_path, user=student, options={"transform": "\n    ".join(rules)}
    )

    assert set(manifest(run.output, ilias.base_url)) == {
        "FOLDER A/A.text",
        # Only the first matching rule applies
        "Gruppe/group.txt",
        "TOP.text",
    }


@pytest.mark.parametrize("redownload", ["never", "never-smart", "always", "always-smart"])
def test_redownload(redownload: str, student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path) -> None:
    options = {"redownload": redownload, "on_conflict": "remote-first"}
    refs = ilias.run_php("changes.php", "create")
    first = run_pferd(refs["course"], tmp_path, user=student, options=options)

    # A local edit that keeps the date of the remote file, so it does not look outdated
    unchanged = first.output / "unchanged.txt"
    stat = unchanged.stat()
    unchanged.write_text("Local edit\n")
    os.utime(unchanged, (stat.st_atime, stat.st_mtime))

    ilias.run_php("changes.php", "change", json.dumps(refs))
    second = run_pferd(refs["course"], tmp_path, user=student, options=options)

    assert second.errors == [], second.log
    changed_content = (second.output / "changed.txt").read_text()
    unchanged_content = unchanged.read_text()
    if redownload == "never":
        assert second.report["changed"] == []
        assert (changed_content, unchanged_content) == ("Content of changed.txt\n", "Local edit\n")
    elif redownload == "always":
        assert sorted(second.report["changed"]) == ["changed.txt", "unchanged.txt"]
        assert (changed_content, unchanged_content) == ("New content\n", "Content of unchanged.txt\n")
    else:
        # The smart variants only download files that are newer in ILIAS
        assert second.report["changed"] == ["changed.txt"]
        assert (changed_content, unchanged_content) == ("New content\n", "Local edit\n")


def test_desktop_contains_favourites(
    desktop_user: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path
) -> None:
    run = run_pferd("desktop", tmp_path, user=desktop_user)

    assert run.warnings == [], run.log
    assert set(manifest(run.output, ilias.base_url)) == {
        "Desktop Course A/a.txt",
        "Favourite Folder/in-folder.txt",
    }


def test_url_target(desktop_user: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path) -> None:
    url = f"{ilias.base_url}/goto.php/fold/{ilias.seed['favourite_folder']}"
    run = run_pferd(url, tmp_path, user=desktop_user)

    assert run.warnings == [], run.log
    assert set(manifest(run.output, ilias.base_url)) == {"in-folder.txt"}


@pytest.mark.xfail(
    reason="CONFIG.md says the 'My Courses' overview downloads all courses, but PFERD does not descend "
    "into courses when crawling an URL",
    strict=True,
)
def test_my_courses_overview_target(
    desktop_user: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path
) -> None:
    url = f"{ilias.base_url}/ilias.php?baseClass=ilmembershipoverviewgui"
    run = run_pferd(url, tmp_path, user=desktop_user)

    assert set(manifest(run.output, ilias.base_url)) == {
        "Desktop Course A/a.txt",
        "Desktop Course B/Favourite Folder/in-folder.txt",
        "Desktop Course B/not-favourite.txt",
    }


def test_invalid_credentials_fail(student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path) -> None:
    run = run_pferd(ilias.course("structure"), tmp_path, user=student, password="wrong", expected_exit_code=1)

    assert "Error Configured credentials are invalid" in run.log
    assert not run.output.exists() or manifest(run.output, ilias.base_url) == {}


@pytest.mark.parametrize(
    ("course", "flags", "expected"),
    [
        (
            "videos",
            ["--videos"],
            {
                "Description.html",
                "Embedded Lecture.mp4",
                "Recordings/Recording 01.mp4",
                "Recordings/Recording 02.mp4",
            },
        ),
        ("videos", ["--no-videos"], {"Description.html"}),
        ("forum", ["--forums"], {"Discussion/Question: Sheet 1?.html", "Discussion/Welcome.html"}),
        ("forum", ["--no-forums"], set()),
        (
            "links",
            ["--links", "plaintext"],
            {
                "KIT Homepage.txt",
                "Office Hours.txt",
                "Useful Links/ILIAS.txt",
                "Useful Links/Python.txt",
                "Useful Links/Rust.txt",
            },
        ),
    ],
)
def test_cli_flags(
    course: str,
    flags: list[str],
    expected: set[str],
    student: str,
    ilias: Ilias,
    tmp_path: Path,
) -> None:
    """
    The ilias-web command instead of a config file.
    """
    credentials = ilias.seed["users"][student]
    credential_file = tmp_path / "credentials"
    credential_file.write_text(f"username={credentials['login']}\npassword={credentials['password']}\n")

    # Neither the output nor the cookies may end up in the current directory
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PFERD",
            "ilias-web",
            "--base-url",
            ilias.base_url,
            "--client-id",
            "default",
            "--credential-file",
            str(credential_file),
            *flags,
            str(ilias.course(course)),
            str(tmp_path / "output"),
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=300,
        cwd=tmp_path,
    )
    log = result.stdout + result.stderr
    assert result.returncode == 0, log

    assert set(manifest(tmp_path / "output", ilias.base_url)) == expected, log
