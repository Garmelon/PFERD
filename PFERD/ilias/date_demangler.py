"""
Helper methods to demangle an ILIAS date.
"""

import datetime
import locale
import logging
import re
from typing import Optional

from ..logging import PrettyLogger

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


def demangle_date(date: str) -> Optional[datetime.datetime]:
    """
    Demangle a given date in one of the following formats:
    "Gestern, HH:MM"
    "Heute, HH:MM"
    "Morgen, HH:MM"
    "dd. mon.yyyy, HH:MM
    """
    saved = locale.setlocale(locale.LC_ALL)
    try:
        locale.setlocale(locale.LC_ALL, 'de_DE.UTF-8')

        date = re.sub(r"\s+", " ", date)
        date = date.replace("Gestern", _yesterday().strftime("%d. %b %Y"))
        date = date.replace("Heute", datetime.date.today().strftime("%d. %b %Y"))
        date = date.replace("Morgen", _tomorrow().strftime("%d. %b %Y"))
        return datetime.datetime.strptime(date, "%d. %b %Y, %H:%M")
    except ValueError:
        PRETTY.warning(f"Could not parse date {date!r}")
        return None
    finally:
        locale.setlocale(locale.LC_ALL, saved)


def _yesterday() -> datetime.date:
    return datetime.date.today() - datetime.timedelta(days=1)


def _tomorrow() -> datetime.date:
    return datetime.date.today() + datetime.timedelta(days=1)
