"""A simple helper for managing downloaded files.

A organizer is bound to a single directory.
"""

import filecmp
import logging
import shutil
from pathlib import Path, PurePath
from typing import List, Set

from .location import Location
from .utils import PrettyLogger, prompt_yes_no

LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


class FileAcceptException(Exception):
    """An exception while accepting a file."""


class Organizer(Location):
    """A helper for managing downloaded files."""

    def __init__(self, path: Path):
        """Create a new organizer for a given path."""
        super().__init__(path)
        self._known_files: Set[Path] = set()

        # Keep the root dir
        self.mark(path)

    def accept_file(self, src: Path, dst: PurePath) -> None:
        """Move a file to this organizer and mark it."""
        src_absolute = src.resolve()
        dst_absolute = self.resolve(dst)

        if not src_absolute.exists():
            raise FileAcceptException("Source file does not exist")

        if not src_absolute.is_file():
            raise FileAcceptException("Source is a directory")

        LOGGER.debug("Copying %s to %s", src_absolute, dst_absolute)

        # Destination file is directory
        if dst_absolute.exists() and dst_absolute.is_dir():
            if prompt_yes_no(f"Overwrite folder {dst_absolute} with file?", default=False):
                shutil.rmtree(dst_absolute)
            else:
                LOGGER.warning("Could not add file %s", dst_absolute)
                return

        # Destination file exists
        if dst_absolute.exists() and dst_absolute.is_file():
            if filecmp.cmp(str(src_absolute), str(dst_absolute), shallow=False):
                # Bail out, nothing more to do
                PRETTY.ignored_file(dst_absolute)
                self.mark(dst)
                return

            PRETTY.modified_file(dst_absolute)
        else:
            PRETTY.new_file(dst_absolute)

        # Create parent dir if needed
        dst_parent_dir: Path = dst_absolute.parent
        dst_parent_dir.mkdir(exist_ok=True, parents=True)

        # Move file
        shutil.move(str(src_absolute), str(dst_absolute))

        self.mark(dst)

    def mark(self, path: PurePath) -> None:
        """Mark a file as used so it will not get cleaned up."""
        absolute_path = self.resolve(path)
        self._known_files.add(absolute_path)
        LOGGER.debug("Tracked %s", absolute_path)

    def cleanup(self) -> None:
        """Remove all untracked files in the organizer's dir."""
        LOGGER.debug("Deleting all untracked files...")

        self._cleanup(self.path)

    def _cleanup(self, start_dir: Path) -> None:
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

    @staticmethod
    def _delete_file_if_confirmed(path: Path) -> None:
        prompt = f"Do you want to delete {path}"

        if prompt_yes_no(prompt, False):
            path.unlink()
