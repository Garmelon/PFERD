"""
An error logging decorator.
"""

import logging
from typing import Any, Callable, TypeVar, cast

from rich.console import Console

from .logging import PrettyLogger

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


class FatalException(Exception):
    """
    A fatal exception occurred. Recovery is not possible.
    """


TFun = TypeVar("TFun", bound=Callable[..., Any])


def swallow_and_print_errors(function: TFun) -> TFun:
    """
    Decorates a function, swallows all errors, logs them and returns none if one occurred.
    """

    def inner(*args: Any, **kwargs: Any) -> Any:
        # pylint: disable=broad-except
        try:
            return function(*args, **kwargs)
        except FatalException as error:
            PRETTY.error(str(error))
            return None
        except Exception as error:
            Console().print_exception()
            return None

    return cast(TFun, inner)


def retry_on_io_exception(max_retries: int, message: str) -> Callable[[TFun], TFun]:
    """
    Decorates a function and retries it on any exception until the max retries count is hit.
    """

    def retry(function: TFun) -> TFun:
        def inner(*args: Any, **kwargs: Any) -> Any:
            for i in range(0, max_retries):
                # pylint: disable=broad-except
                try:
                    return function(*args, **kwargs)
                except IOError as error:
                    PRETTY.warning(
                        f"Error duing operation '{message}': {error}")
                    PRETTY.warning(
                        f"Retrying operation '{message}'. Remaining retries: {max_retries - 1 - i}"
                    )

        return cast(TFun, inner)

    return retry
