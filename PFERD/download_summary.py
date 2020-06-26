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
        self.new_files: List[Path] = []
        self.modified_files: List[Path] = []
        self.deleted_files: List[Path] = []

    def merge(self, summary: 'DownloadSummary') -> None:
        """
        Merges ourselves with the passed summary. Modifies this object, but not the passed one.
        """
        self.new_files += summary.new_files
        self.modified_files += summary.modified_files
        self.deleted_files += summary.deleted_files

    def add_deleted_file(self, path: Path) -> None:
        """
        Registers a file as deleted.
        """
        self.deleted_files.append(path)

    def add_modified_file(self, path: Path) -> None:
        """
        Registers a file as changed.
        """
        self.modified_files.append(path)

    def add_new_file(self, path: Path) -> None:
        """
        Registers a file as new.
        """
        self.new_files.append(path)

    def has_updates(self) -> bool:
        """
        Returns whether this summary has any updates.
        """
        return bool(self.new_files or self.modified_files or self.deleted_files)
