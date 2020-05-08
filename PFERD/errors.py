"""
An error logging decorator.
"""

import logging
from typing import Any, Callable

from rich.console import Console

from .logging import FatalException, PrettyLogger

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


def swallow_and_print_errors(function: Callable) -> Callable:
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
    return inner
