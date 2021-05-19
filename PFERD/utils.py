import asyncio
import contextvars
import functools
import getpass
import sys
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from types import TracebackType
from typing import Any, Callable, Generic, Optional, Type, TypeVar

import bs4

T = TypeVar("T")


# TODO When switching to 3.9, use asyncio.to_thread instead of this
async def to_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    # https://github.com/python/cpython/blob/8d47f92d46a92a5931b8f3dcb4a484df672fc4de/Lib/asyncio/threads.py
    loop = asyncio.get_event_loop()
    ctx = contextvars.copy_context()
    func_call = functools.partial(ctx.run, func, *args, **kwargs)
    return await loop.run_in_executor(None, func_call)  # type: ignore


async def ainput(prompt: str) -> str:
    return await to_thread(lambda: input(prompt))


async def agetpass(prompt: str) -> str:
    return await to_thread(lambda: getpass.getpass(prompt))


def soupify(data: bytes) -> bs4.BeautifulSoup:
    """
    Parses HTML to a beautifulsoup object.
    """

    return bs4.BeautifulSoup(data, "html.parser")


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
