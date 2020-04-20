import logging

# from .ilias import *
# from .utils import *
from .temp_folder import *

STYLE = "{"
FORMAT = "[{levelname:<7}] {message}"
DATE_FORMAT = "%F %T"

FORMATTER = logging.Formatter(
    fmt=FORMAT,
    datefmt=DATE_FORMAT,
    style=STYLE,
)


def enable_logging(name: str = "PFERD", level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(FORMATTER)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    # This should be logged by our own handler, and not the root logger's
    # default handler, so we don't pass it on to the root logger.
    logger.propagate = False
