"""
Provides a summary that keeps track of new modified or deleted files.
"""
from pathlib import Path
from typing import List


class DownloadSummary:
    """
    Keeps track of all new, modified or deleted files and provides a summary.
    """

    def __init__(self) -> None:
        self._new_files: List[Path] = []
        self._modified_files: List[Path] = []
        self._deleted_files: List[Path] = []

    @property
    def new_files(self) -> List[Path]:
        """
        Returns all new files.
        """
        return self._new_files.copy()

    @property
    def modified_files(self) -> List[Path]:
        """
        Returns all modified files.
        """
        return self._modified_files.copy()

    @property
    def deleted_files(self) -> List[Path]:
        """
        Returns all deleted files.
        """
        return self._deleted_files.copy()

    def merge(self, summary: 'DownloadSummary') -> None:
        """
        Merges ourselves with the passed summary. Modifies this object, but not the passed one.
        """
        self._new_files += summary.new_files
        self._modified_files += summary.modified_files
        self._deleted_files += summary.deleted_files

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

    def has_updates(self) -> bool:
        """
        Returns whether this summary has any updates.
        """
        return bool(self._new_files or self._modified_files or self._deleted_files)
