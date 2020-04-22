"""
Helper methods to demangle an ILIAS date.
"""

import datetime
import re


def demangle_date(date: str) -> datetime.datetime:
    """
    Demangle a given date in one of the following formats:
    "Gestern, HH:MM"
    "Heute, HH:MM"
    "dd. mon.yyyy, HH:MM
    """
    date = re.sub(r"\s+", " ", date)
    date = date.replace("Gestern", _yesterday().strftime("%d. %b %Y"))
    date = date.replace("Heute", datetime.date.today().strftime("%d. %b %Y"))

    return datetime.datetime.strptime(date, "%d. %b %Y, %H:%M")


def _yesterday() -> datetime.date:
    return datetime.date.today() - datetime.timedelta(days=1)
