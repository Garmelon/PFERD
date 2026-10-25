"""
Tells the user about new PFERD releases. GitHub is asked at most once a day, the answer is cached in
the user's cache directory.
"""

import json
import os
import ssl
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

import aiohttp
import certifi

from . import __version__
from .logging import log

REPO_URL = "https://api.github.com/repos/Garmelon/PFERD"
# Setting this to any non-empty value disables the update check, regardless of the config
DISABLE_ENV_VAR = "PFERD_NO_UPDATE_CHECK"
CHECK_INTERVAL_SECS = 24 * 60 * 60
TIMEOUT_SECS = 5


def disabled_by_env() -> bool:
    return bool(os.environ.get(DISABLE_ENV_VAR))


def default_cache_file() -> Path:
    if os.name == "nt":
        cache_dir = os.environ.get("LOCALAPPDATA") or "~/AppData/Local"
    else:
        cache_dir = os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    return Path(cache_dir).expanduser() / "PFERD" / "update-check.json"


def is_newer(version: str, current: str = __version__) -> bool:
    """
    Whether the version is newer than the current one. Versions that are no numbers separated by dots
    (like "unknown") are never newer.
    """
    new, old = _parse_version(version), _parse_version(current)
    return new is not None and old is not None and new > old


def _parse_version(version: str) -> Optional[tuple[int, ...]]:
    try:
        return tuple(int(part) for part in version.removeprefix("v").split("."))
    except ValueError:
        return None


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    # The message of the release's tag, which lists the changes
    notes: Optional[str]


async def newest_release(repo_url: str = REPO_URL, cache_file: Optional[Path] = None) -> Optional[Release]:
    """
    The newest release, or None if it is unknown. Never throws, as the update check should never break
    a run.
    """
    log.explain_topic("Checking for updates")
    cache_file = cache_file or default_cache_file()
    checked_at, release = _read_cache(cache_file)
    if checked_at is not None and time.time() - checked_at < CHECK_INTERVAL_SECS:
        log.explain(f"Checked recently, the newest release is {release}")
        return release

    try:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where())),
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECS),
            headers={"Accept": "application/vnd.github+json", "User-Agent": f"PFERD/{__version__}"},
        ) as session:
            release = await _fetch_newest_release(session, repo_url)
        log.explain(f"The newest release is {release}")
    except Exception as e:
        # Also remember failed checks, so we don't ask GitHub on every run while it is unreachable
        log.explain(f"Could not check for updates: {e}")

    _write_cache(cache_file, release)
    return release


async def _fetch_newest_release(session: aiohttp.ClientSession, repo_url: str) -> Release:
    release = await _get_json(session, f"{repo_url}/releases/latest")
    tag = str(release["tag_name"])
    version = tag.removeprefix("v")

    notes = None
    # Only users that can update see the notes, so save the requests otherwise
    if is_newer(version):
        try:
            notes = await _fetch_tag_message(session, repo_url, tag)
        except Exception as e:
            log.explain(f"Could not fetch the changes of {tag}: {e}")

    return Release(version=version, url=str(release["html_url"]), notes=notes)


async def _fetch_tag_message(session: aiohttp.ClientSession, repo_url: str, tag: str) -> Optional[str]:
    ref = await _get_json(session, f"{repo_url}/git/ref/tags/{tag}")
    # Lightweight tags point directly to a commit and have no message
    if ref["object"]["type"] != "tag":
        return None
    annotated_tag = await _get_json(session, str(ref["object"]["url"]))
    return str(annotated_tag["message"]).strip()


async def _get_json(session: aiohttp.ClientSession, url: str) -> Any:
    async with session.get(url) as resp:
        resp.raise_for_status()
        return await resp.json()


def _read_cache(cache_file: Path) -> tuple[Optional[float], Optional[Release]]:
    try:
        cache = json.loads(cache_file.read_text())
        release = Release(**cache["release"]) if cache["release"] is not None else None
        return float(cache["checked_at"]), release
    except (OSError, ValueError, KeyError, TypeError):
        return None, None


def _write_cache(cache_file: Path, release: Optional[Release]) -> None:
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache = {"checked_at": time.time(), "release": asdict(release) if release is not None else None}
        cache_file.write_text(json.dumps(cache))
    except OSError as e:
        # Then we just check again next time
        log.explain(f"Could not remember the update check in {cache_file}: {e}")
