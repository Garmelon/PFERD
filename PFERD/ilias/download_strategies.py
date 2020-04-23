"""
Contains a few default strategies for limiting the amount of downloaded files.
"""

import logging
from typing import Callable

from ..organizer import Organizer
from ..utils import PrettyLogger
from .downloader import IliasDownloadInfo

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)

DownloadStrategy = Callable[[Organizer, IliasDownloadInfo], bool]


def download_everything(organizer: Organizer, info: IliasDownloadInfo) -> bool:
    # pylint: disable=unused-argument
    """
    Accepts everything.
    """
    return True


def download_modified_or_new(organizer: Organizer, info: IliasDownloadInfo) -> bool:
    """
    Accepts new files or files with a more recent modification date.
    """
    resolved_file = organizer.resolve(info.path)
    if not resolved_file.exists() or info.modification_date is None:
        return True
    resolved_mod_time_seconds = resolved_file.stat().st_mtime

    # Download if the info is newer
    if info.modification_date.timestamp() > resolved_mod_time_seconds:
        return True

    PRETTY.filtered_path(info.path, "Local file had newer or equal modification time")
    return False
