"""A simple helper for managing downloaded files.

A organizer is bound to a single directory.
"""

import filecmp
import logging
import os
import shutil
from enum import Enum
from pathlib import Path, PurePath
from typing import Callable, List, Optional, Set

from .download_summary import DownloadSummary
from .location import Location
from .logging import PrettyLogger
from .utils import prompt_yes_no

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


class ConflictType(Enum):
    """
    The type of the conflict. A file might not exist anymore and will be deleted
    or it might be overwritten with a newer version.

    FILE_OVERWRITTEN: An existing file will be updated
    MARKED_FILE_OVERWRITTEN: A file is written for the second+ time in this run
    FILE_DELETED: The file was deleted
    """
    FILE_OVERWRITTEN = "overwritten"
    MARKED_FILE_OVERWRITTEN = "marked_file_overwritten"
    FILE_DELETED = "deleted"


class FileConflictResolution(Enum):
    """
    The reaction when confronted with a file conflict:

    DESTROY_EXISTING: Delete/overwrite the current file
    KEEP_EXISTING: Keep the current file
    DEFAULT: Do whatever the PFERD authors thought is sensible
    PROMPT: Interactively ask the user
    """

    DESTROY_EXISTING = "destroy"

    KEEP_EXISTING = "keep"

    DEFAULT = "default"

    PROMPT = "prompt"


FileConflictResolver = Callable[[PurePath, ConflictType], FileConflictResolution]


def resolve_prompt_user(_path: PurePath, conflict: ConflictType) -> FileConflictResolution:
    """
    Resolves conflicts by asking the user if a file was written twice or will be deleted.
    """
    if conflict == ConflictType.FILE_OVERWRITTEN:
        return FileConflictResolution.DESTROY_EXISTING
    return FileConflictResolution.PROMPT


class FileAcceptException(Exception):
    """An exception while accepting a file."""


class Organizer(Location):
    """A helper for managing downloaded files."""

    def __init__(self, path: Path, conflict_resolver: FileConflictResolver = resolve_prompt_user):
        """Create a new organizer for a given path."""
        super().__init__(path)
        self._known_files: Set[Path] = set()

        # Keep the root dir
        self._known_files.add(path.resolve())

        self.download_summary = DownloadSummary()

        self.conflict_resolver = conflict_resolver

    def accept_file(self, src: Path, dst: PurePath) -> Optional[Path]:
        """
        Move a file to this organizer and mark it.

        Returns the path the file was moved to, to allow the caller to adjust the metadata.
        As you might still need to adjust the metadata when the file was identical
        (e.g. update the timestamp), the path is also returned in this case.
        In all other cases (ignored, not overwritten, etc.) this method returns None.
        """
        # Windows limits the path length to 260 for *some* historical reason
        # If you want longer paths, you will have to add the "\\?\" prefix in front of
        # your path...
        # See:
        # https://docs.microsoft.com/en-us/windows/win32/fileio/naming-a-file#maximum-path-length-limitation
        if os.name == 'nt':
            src_absolute = Path("\\\\?\\" + str(src.resolve()))
            dst_absolute = Path("\\\\?\\" + str(self.resolve(dst)))
        else:
            src_absolute = src.resolve()
            dst_absolute = self.resolve(dst)

        if not src_absolute.exists():
            raise FileAcceptException("Source file does not exist")

        if not src_absolute.is_file():
            raise FileAcceptException("Source is a directory")

        LOGGER.debug("Copying %s to %s", src_absolute, dst_absolute)

        if self._is_marked(dst):
            PRETTY.warning(f"File {str(dst_absolute)!r} was already written!")
            conflict = ConflictType.MARKED_FILE_OVERWRITTEN
            if self._resolve_conflict(f"Overwrite file?", dst_absolute, conflict, default=False):
                PRETTY.ignored_file(dst_absolute, "file was written previously")
                return None

        # Destination file is directory
        if dst_absolute.exists() and dst_absolute.is_dir():
            prompt = f"Overwrite folder {dst_absolute} with file?"
            conflict = ConflictType.FILE_OVERWRITTEN
            if self._resolve_conflict(prompt, dst_absolute, conflict, default=False):
                shutil.rmtree(dst_absolute)
            else:
                PRETTY.warning(f"Could not add file {str(dst_absolute)!r}")
                return None

        # Destination file exists
        if dst_absolute.exists() and dst_absolute.is_file():
            if filecmp.cmp(str(src_absolute), str(dst_absolute), shallow=False):
                # Bail out, nothing more to do
                PRETTY.ignored_file(dst_absolute, "same file contents")
                self.mark(dst)
                return dst_absolute

            prompt = f"Overwrite file {dst_absolute}?"
            conflict = ConflictType.FILE_OVERWRITTEN
            if not self._resolve_conflict(prompt, dst_absolute, conflict, default=True):
                return None

            self.download_summary.add_modified_file(dst_absolute)
            PRETTY.modified_file(dst_absolute)
        else:
            self.download_summary.add_new_file(dst_absolute)
            PRETTY.new_file(dst_absolute)

        # Create parent dir if needed
        dst_parent_dir: Path = dst_absolute.parent
        dst_parent_dir.mkdir(exist_ok=True, parents=True)

        # Move file
        shutil.move(str(src_absolute), str(dst_absolute))

        self.mark(dst)

        return dst_absolute

    def mark(self, path: PurePath) -> None:
        """Mark a file as used so it will not get cleaned up."""
        absolute_path = self.resolve(path)
        self._known_files.add(absolute_path)
        LOGGER.debug("Tracked %s", absolute_path)

    def _is_marked(self, path: PurePath) -> bool:
        """
        Checks whether a file is marked.
        """
        absolute_path = self.resolve(path)
        return absolute_path in self._known_files

    def cleanup(self) -> None:
        """Remove all untracked files in the organizer's dir."""
        LOGGER.debug("Deleting all untracked files...")

        self._cleanup(self.path)

    def _cleanup(self, start_dir: Path) -> None:
        if not start_dir.exists():
            return
        paths: List[Path] = list(start_dir.iterdir())

        # Recursively clean paths
        for path in paths:
            if path.is_dir():
                self._cleanup(path)
            else:
                if path.resolve() not in self._known_files:
                    self._delete_file_if_confirmed(path)

        # Delete dir if it was empty and untracked
        dir_empty = len(list(start_dir.iterdir())) == 0
        if start_dir.resolve() not in self._known_files and dir_empty:
            start_dir.rmdir()

    def _delete_file_if_confirmed(self, path: Path) -> None:
        prompt = f"Do you want to delete {path}"

        if self._resolve_conflict(prompt, path, ConflictType.FILE_DELETED, default=False):
            self.download_summary.add_deleted_file(path)
            path.unlink()

    def _resolve_conflict(
            self, prompt: str, path: Path, conflict: ConflictType, default: bool
    ) -> bool:
        if not self.conflict_resolver:
            return prompt_yes_no(prompt, default=default)

        result = self.conflict_resolver(path, conflict)
        if result == FileConflictResolution.DEFAULT:
            return default
        if result == FileConflictResolution.KEEP_EXISTING:
            return False
        if result == FileConflictResolution.DESTROY_EXISTING:
            return True

        return prompt_yes_no(prompt, default=default)
