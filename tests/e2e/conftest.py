"""
Fixtures for the end-to-end tests, which crawl a local ILIAS instance running in docker (see stack.py).
"""

import json
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol

import pytest

from . import stack
from .stack import Ilias

# The users seed.php creates for each language. KIT users see ILIAS in either language.
STUDENTS = {"en": "student", "de": "studentin"}
DESKTOP_USERS = {"en": "desktop", "de": "schreibtisch"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    e2e_dir = Path(__file__).parent
    for item in items:
        if e2e_dir in item.path.parents:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session")
def ilias() -> Iterator[Ilias]:
    yield stack.get_or_start()


@pytest.fixture(params=STUDENTS.keys())
def student(request: pytest.FixtureRequest) -> str:
    """
    A student that is a member of all courses. Tests using this run once per language.
    """
    return STUDENTS[request.param]


@pytest.fixture(params=DESKTOP_USERS.keys())
def desktop_user(request: pytest.FixtureRequest) -> str:
    """
    A user with only a few courses and favourites. Tests using this run once per language.
    """
    return DESKTOP_USERS[request.param]


@dataclass(frozen=True)
class PferdRun:
    output: Path
    report: dict[str, Any]
    log: str

    @property
    def warnings(self) -> list[str]:
        # Not all warnings end up in the report, so look at what the user sees
        return [line.strip() for line in self.log.splitlines() if line.lstrip().startswith("Warning ")]

    @property
    def errors(self) -> list[str]:
        return self.report["encountered_errors"]


class RunPferd(Protocol):
    def __call__(
        self,
        target: int | str,
        working_dir: Path,
        user: str,
        options: Optional[dict[str, str]] = None,
        password: Optional[str] = None,
        expected_exit_code: int = 0,
    ) -> PferdRun: ...


@pytest.fixture
def run_pferd(ilias: Ilias) -> RunPferd:
    """
    Runs PFERD on the given target (a course id, an URL or "desktop"), downloading into
    "<working_dir>/course". Running it again with the same working dir updates the previous download.
    The password defaults to the one of the user.
    """

    def run(
        target: int | str,
        working_dir: Path,
        user: str,
        options: Optional[dict[str, str]] = None,
        password: Optional[str] = None,
        expected_exit_code: int = 0,
    ) -> PferdRun:
        credentials = ilias.seed["users"][user]
        working_dir.mkdir(parents=True, exist_ok=True)
        config = working_dir / "pferd.cfg"
        config.write_text(
            f"[DEFAULT]\n"
            f"working_dir = {working_dir}\n"
            f"\n"
            f"[auth:user]\n"
            f"type = simple\n"
            f"username = {credentials['login']}\n"
            f"password = {password or credentials['password']}\n"
            f"\n"
            f"[crawl:course]\n"
            f"type = ilias-web\n"
            f"base_url = {ilias.base_url}\n"
            f"login_type = local\n"
            f"client_id = default\n"
            f"auth = auth:user\n"
            f"target = {target}\n" + "".join(f"{key} = {value}\n" for key, value in (options or {}).items())
        )

        result = subprocess.run(
            [sys.executable, "-m", "PFERD", "-c", str(config)],
            capture_output=True,
            text=True,
            # Fail instead of waiting forever if PFERD prompts for something
            stdin=subprocess.DEVNULL,
            timeout=300,
        )
        log = result.stdout + result.stderr
        assert result.returncode == expected_exit_code, f"PFERD exited with {result.returncode}:\n{log}"

        output = working_dir / "course"
        report_path = output / ".report"
        # Aborted crawlers write no report
        if expected_exit_code != 0 and not report_path.exists():
            return PferdRun(output=output, report={}, log=log)
        assert report_path.exists(), f"PFERD wrote no report:\n{log}"
        report = json.loads(report_path.read_text())
        return PferdRun(output=output, report=report, log=log)

    return run
