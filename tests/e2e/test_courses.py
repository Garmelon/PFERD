"""
Crawls every fixture course and compares the result to a snapshot. Update the snapshots with
"pytest -n 0 --snapshot-update" after intentional changes and review the diff. Under pytest-xdist,
syrupy deletes the snapshots of the tests other workers ran as unused.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pytest
from _pytest.mark import ParameterSet
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.json import JSONSnapshotExtension

from .conftest import Ilias, RunPferd
from .manifest import manifest

# Known PFERD bugs. Tests affected by them are marked as strict xfail, so they start failing once the
# bug is fixed. Then remove the mark (and update the snapshot).
UNAVAILABLE_FILE_BUG = (
    "Files that are not available yet link to the info screen and have no file icon, so PFERD warns "
    "that it can not determine their type"
)
SESSION_HIDE_LINK_BUG = (
    "After expanding all sessions, PFERD treats the 'Hide previous/upcoming sessions' links as folders "
    "and crawls into them"
)


@dataclass(frozen=True)
class Case:
    id: str
    course: str
    options: dict[str, str] = field(default_factory=dict)
    # Reason why PFERD currently produces warnings for this case
    known_warnings: Optional[str] = None


CASES = [
    Case("structure", "structure"),
    Case("naming", "naming"),
    Case("dates", "dates"),
    Case("page_content", "page_content"),
    Case("content_page", "content_page"),
    Case("videos", "videos", options={"videos": "true"}),
    Case("videos_disabled", "videos"),
    Case("links_fancy", "links", options={"links": "fancy"}),
    Case("links_plaintext", "links", options={"links": "plaintext"}),
    Case("links_internet_shortcut", "links", options={"links": "internet-shortcut"}),
    Case("links_ignore", "links", options={"links": "ignore"}),
    Case("unsupported", "unsupported"),
    Case("availability", "availability", known_warnings=UNAVAILABLE_FILE_BUG),
    Case("sessions", "sessions", known_warnings=SESSION_HIDE_LINK_BUG),
    Case("exercises", "exercises"),
    Case("forum", "forum", options={"forums": "true"}),
    Case("forum_disabled", "forum"),
    Case("learning_module", "learning_module"),
    Case("kit_lecture", "kit_lecture"),
    Case("kit_seminar", "kit_seminar"),
    Case("kit_collapsed_groups", "kit_collapsed_groups"),
    Case("kit_weekly_accordions", "kit_weekly_accordions"),
    Case("nesting", "nesting"),
]


def _cases(xfail_known_warnings: bool = False) -> list[ParameterSet]:
    params: list[ParameterSet] = []
    for case in CASES:
        marks: list[pytest.MarkDecorator] = []
        if xfail_known_warnings and case.known_warnings:
            marks.append(pytest.mark.xfail(reason=case.known_warnings, strict=True))
        params.append(pytest.param(case, id=case.id, marks=marks))
    return params


@pytest.fixture
def snapshot_json(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    return snapshot.use_extension(JSONSnapshotExtension)


@pytest.mark.parametrize("case", _cases())
def test_course_tree(
    case: Case,
    student: str,
    ilias: Ilias,
    run_pferd: RunPferd,
    tmp_path: Path,
    snapshot_json: SnapshotAssertion,
) -> None:
    run = run_pferd(ilias.course(case.course), tmp_path, user=student, options=case.options)

    assert run.errors == [], run.log
    assert manifest(run.output, ilias.base_url) == snapshot_json


@pytest.mark.parametrize("case", _cases(xfail_known_warnings=True))
def test_course_without_warnings(
    case: Case, student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path
) -> None:
    run = run_pferd(ilias.course(case.course), tmp_path, user=student, options=case.options)

    assert run.warnings == [], run.log


@pytest.mark.parametrize("case", _cases())
def test_second_run_changes_nothing(
    case: Case, student: str, ilias: Ilias, run_pferd: RunPferd, tmp_path: Path
) -> None:
    first = run_pferd(ilias.course(case.course), tmp_path, user=student, options=case.options)
    second = run_pferd(ilias.course(case.course), tmp_path, user=student, options=case.options)

    assert second.errors == [], second.log
    assert second.report["added"] == []
    assert second.report["changed"] == []
    assert second.report["deleted"] == []
    assert manifest(second.output, ilias.base_url) == manifest(first.output, ilias.base_url)
