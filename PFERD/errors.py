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


TFun = TypeVar('TFun', bound=Callable[..., Any])


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
