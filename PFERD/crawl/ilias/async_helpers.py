import aiohttp
import asyncio
from typing import Any, Callable, Optional

from ...logging import log
from ..crawler import AWrapped, CrawlError, CrawlWarning


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
