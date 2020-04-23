"""
Contains a few default strategies for limiting the amount of downloaded files.
"""

import datetime
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from typing_extensions import Protocol, runtime_checkable

from .organizer import Organizer
from .utils import PrettyLogger

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


@runtime_checkable
class DownloadInfo(Protocol):
    # pylint: disable=too-few-public-methods
    """
    This class describes some minimal information about a file you can download.
    """

    @property
    def path(self) -> Path:
        """
        Returns the path.
        """

    @property
    def modification_date(self) -> Optional[datetime.datetime]:
        """
        Returns the modification date or None if not known.
        """


class DownloadStrategy(ABC):
    # pylint: disable=too-few-public-methods
    """
    A strategy deciding whether to download a given info.
    """

    @abstractmethod
    def should_download(self, organizer: Organizer, info: DownloadInfo) -> bool:
        """
        Decides wether a given file should be downloaded.
        """


class DownloadEverythingStrategy(DownloadStrategy):
    # pylint: disable=too-few-public-methods
    """
    A strategy that redownloads everything.
    """

    def should_download(self, organizer: Organizer, info: DownloadInfo) -> bool:
        return True


class DownloadNewOrModified(DownloadStrategy):
    # pylint: disable=too-few-public-methods
    """
    A strategy that only downloads changed or new files.
    """

    def should_download(self, organizer: Organizer, info: DownloadInfo) -> bool:
        resolved_file = organizer.resolve(info.path)
        if not resolved_file.exists() or info.modification_date is None:
            return True
        resolved_mod_time_seconds = resolved_file.stat().st_mtime

        # Download if the info is newer
        if info.modification_date.timestamp() > resolved_mod_time_seconds:
            return True

        PRETTY.filtered_path(info.path, "Local file had newer or equal modification time")
        return False
