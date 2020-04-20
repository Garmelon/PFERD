"""
This module exports only what you need for a basic configuration. If you want a
more complex configuration, you need to import the other submodules manually.
"""

import logging

STYLE = "{"
FORMAT = "[{levelname:<7}] {message}"
DATE_FORMAT = "%F %T"

FORMATTER = logging.Formatter(
    fmt=FORMAT,
    datefmt=DATE_FORMAT,
    style=STYLE,
)


def enable_logging(name: str = "PFERD", level: int = logging.INFO) -> None:
    """
    Enable and configure logging via the logging module.
    """

    handler = logging.StreamHandler()
    handler.setFormatter(FORMATTER)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    # This should be logged by our own handler, and not the root logger's
    # default handler, so we don't pass it on to the root logger.
    logger.propagate = False
