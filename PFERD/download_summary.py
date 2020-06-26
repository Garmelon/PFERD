"""
Provides a summary that keeps track of new modified or deleted files.
"""
import logging
from pathlib import Path
from typing import List

from .logging import PrettyLogger


class DownloadSummary:
    """
    Keeps track of all new, modified or deleted files and provides a summary.
    """

    def __init__(self) -> None:
        self._new_files: List[Path] = []
        self._modified_files: List[Path] = []
        self._deleted_files: List[Path] = []

    def merge(self, summary: 'DownloadSummary') -> None:
        """
        Merges ourselves with the passed summary. Modifies this object, but not the passed one.
        """
        # This is our own class!
        # pylint: disable=protected-access
        self._new_files += summary._new_files
        self._modified_files += summary._modified_files
        self._deleted_files += summary._deleted_files

    def add_deleted_file(self, path: Path) -> None:
        """
        Registers a file as deleted.
        """
        self._deleted_files.append(path)

    def add_modified_file(self, path: Path) -> None:
        """
        Registers a file as changed.
        """
        self._modified_files.append(path)

    def add_new_file(self, path: Path) -> None:
        """
        Registers a file as new.
        """
        self._new_files.append(path)

    def _has_updates(self) -> bool:
        return bool(self._new_files or self._modified_files or self._deleted_files)

    def print(self, logger: logging.Logger, pretty: PrettyLogger) -> None:
        """
        Prints this summary.
        """
        logger.info("")
        logger.info("Summary: ")
        if not self._has_updates():
            logger.info("Nothing changed!")
            return

        if self._new_files:
            logger.info("New Files:")
            for file in self._new_files:
                pretty.new_file(file)

        logger.info("")

        if self._modified_files:
            logger.info("Modified Files:")
            for file in self._modified_files:
                pretty.modified_file(file)

        logger.info("")

        if self._deleted_files:
            logger.info("Deleted Files:")
            for file in self._deleted_files:
                pretty.deleted_file(file)
