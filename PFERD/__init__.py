import logging

from .ffm import *
from .ilias import *
from .norbert import *
from .ti import *
from .utils import *

__all__ = ["STYLE", "FORMAT", "DATE_FORMAT", "FORMATTER", "enable_logging"]

__all__ += ffm.__all__
__all__ += ilias.__all__
__all__ += norbert.__all__
__all__ += ti.__all__
__all__ += utils.__all__

STYLE = "{"
FORMAT = "[{levelname:<7}] {message}"
DATE_FORMAT = "%F %T"

FORMATTER = logging.Formatter(
        fmt=FORMAT,
        datefmt=DATE_FORMAT,
        style=STYLE,
)

def enable_logging(name="PFERD", level=logging.INFO):
    handler = logging.StreamHandler()
    handler.setFormatter(FORMATTER)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    # This should be logged by our own handler, and not the root logger's
    # default handler, so we don't pass it on to the root logger.
    logger.propagate = False
