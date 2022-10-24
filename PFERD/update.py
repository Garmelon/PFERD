from dataclasses import dataclass
import ssl
from typing import Optional
import aiohttp
import certifi

from .version import NAME, VERSION
from .logging import log


@dataclass
class PferdUpdate:
    release_url: str
    version: str


def _build_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        headers={"User-Agent": f"{NAME}/{VERSION}"},
        connector=aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where())),
        timeout=aiohttp.ClientTimeout(
            total=15 * 60,
            connect=10,
            sock_connect=10,
            sock_read=10,
        )
    )


async def check_for_updates() -> None:
    if new_version := await get_newer_version():
        log.warn(
            f"{NAME} version out of date. "
            + f"You are running version {VERSION!r} but {new_version.version!r} was found on GitHub."
        )
        log.warn_contd(f"You can download it on GitHub: {new_version.release_url}")
    else:
        log.explain("No update found")


async def get_newer_version() -> Optional[PferdUpdate]:
    async with _build_session() as session:
        async with session.get(
            "https://api.github.com/repos/Garmelon/Pferd/releases/latest",
            headers={"Accept": "application/vnd.github+json"}
        ) as response:
            release_information = await response.json()
            tag_name: str = release_information["tag_name"]
            tag_name = tag_name.removeprefix("v")
            if VERSION == tag_name:
                return None

            return PferdUpdate(release_url=release_information["html_url"], version=tag_name)
