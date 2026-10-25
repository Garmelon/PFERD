import pytest

from .e2e import stack


def _is_xdist_worker(config: pytest.Config) -> bool:
    return hasattr(config, "workerinput")


# These hooks live here instead of in e2e/conftest.py, as the xdist controller does not collect tests
# and thereby never loads e2e/conftest.py.


def pytest_configure(config: pytest.Config) -> None:
    if not _is_xdist_worker(config):
        stack.create_state_dir()


def pytest_sessionfinish(session: pytest.Session) -> None:
    if not _is_xdist_worker(session.config):
        stack.stop()
