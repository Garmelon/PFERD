import asyncio
import getpass
import sys
import threading
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from pathlib import Path, PurePath
from types import TracebackType
from typing import Any, Callable, Dict, Generic, Optional, Type, TypeVar
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import aiohttp
import bs4

from .crawl.crawler import AWrapped, CrawlError, CrawlWarning
from .logging import log

T = TypeVar("T")


def _iorepeat(attempts: int, name: str, failure_is_error: bool = False) -> Callable[[AWrapped], AWrapped]:
    def decorator(f: AWrapped) -> AWrapped:
        async def wrapper(*args: Any, **kwargs: Any) -> Optional[Any]:
            last_exception: Optional[BaseException] = None
            for round in range(attempts):
                try:
                    return await f(*args, **kwargs)
                except aiohttp.ContentTypeError:  # invalid content type
                    raise CrawlWarning("ILIAS returned an invalid content type")
                except aiohttp.TooManyRedirects:
                    raise CrawlWarning("Got stuck in a redirect loop")
                except aiohttp.ClientPayloadError as e:  # encoding or not enough bytes
                    last_exception = e
                except aiohttp.ClientConnectionError as e:  # e.g. timeout, disconnect, resolve failed, etc.
                    last_exception = e
                except asyncio.exceptions.TimeoutError as e:  # explicit http timeouts in HttpCrawler
                    last_exception = e
                log.explain_topic(f"Retrying operation {name}. Retries left: {attempts - 1 - round}")

            if last_exception:
                message = f"Error in I/O Operation: {last_exception}"
                if failure_is_error:
                    raise CrawlError(message) from last_exception
                else:
                    raise CrawlWarning(message) from last_exception
            raise CrawlError("Impossible return in ilias _iorepeat")

        return wrapper  # type: ignore

    return decorator


async def in_daemon_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = asyncio.Future()

    def thread_func() -> None:
        result = func()
        loop.call_soon_threadsafe(future.set_result, result)

    threading.Thread(target=thread_func, daemon=True).start()

    return await future


async def ainput(prompt: str) -> str:
    return await in_daemon_thread(lambda: input(prompt))


async def agetpass(prompt: str) -> str:
    return await in_daemon_thread(lambda: getpass.getpass(prompt))


async def prompt_yes_no(query: str, default: Optional[bool]) -> bool:
    """
    Asks the user a yes/no question and returns their choice.
    """

    if default is True:
        query += " [Y/n] "
    elif default is False:
        query += " [y/N] "
    else:
        query += " [y/n] "

    while True:
        response = (await ainput(query)).strip().lower()
        if response == "y":
            return True
        elif response == "n":
            return False
        elif response == "" and default is not None:
            return default

        print("Please answer with 'y' or 'n'.")


def soupify(data: bytes) -> bs4.BeautifulSoup:
    """
    Parses HTML to a beautifulsoup object.
    """

    return bs4.BeautifulSoup(data, "html.parser")


def url_set_query_param(url: str, param: str, value: str) -> str:
    """
    Set a query parameter in an url, overwriting existing ones with the same name.
    """
    scheme, netloc, path, query, fragment = urlsplit(url)
    query_parameters = parse_qs(query)
    query_parameters[param] = [value]
    new_query_string = urlencode(query_parameters, doseq=True)

    return urlunsplit((scheme, netloc, path, new_query_string, fragment))


def url_set_query_params(url: str, params: Dict[str, str]) -> str:
    """
    Sets multiple query parameters in an url, overwriting existing ones.
    """
    result = url

    for key, val in params.items():
        result = url_set_query_param(result, key, val)

    return result


def str_path(path: PurePath) -> str:
    if not path.parts:
        return "."
    return "/".join(path.parts)


def fmt_path(path: PurePath) -> str:
    return repr(str_path(path))


def fmt_real_path(path: Path) -> str:
    return repr(str(path.absolute()))


class ReusableAsyncContextManager(ABC, Generic[T]):
    def __init__(self) -> None:
        self._active = False
        self._stack = AsyncExitStack()

    @abstractmethod
    async def _on_aenter(self) -> T:
        pass

    async def __aenter__(self) -> T:
        if self._active:
            raise RuntimeError("Nested or otherwise concurrent usage is not allowed")

        self._active = True
        await self._stack.__aenter__()

        # See https://stackoverflow.com/a/13075071
        try:
            result: T = await self._on_aenter()
        except:  # noqa: E722 do not use bare 'except'
            if not await self.__aexit__(*sys.exc_info()):
                raise

        return result

    async def __aexit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc_value: Optional[BaseException],
            traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        if not self._active:
            raise RuntimeError("__aexit__ called too many times")

        result = await self._stack.__aexit__(exc_type, exc_value, traceback)
        self._active = False
        return result
