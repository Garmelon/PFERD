"""A simple helper for managing downloaded files.

A organizer is bound to a single directory.
"""

import filecmp
import logging
import shutil
from pathlib import Path
from typing import List, Set

from .utils import PrettyLogger, prompt_yes_no, resolve_path

logger = logging.getLogger(__name__)
pretty_logger = PrettyLogger(logger)


class FileAcceptException(Exception):
    """An exception while accepting a file."""

    def __init__(self, message: str):
        """Create a new exception."""
        super().__init__(message)


class Organizer():
    """A helper for managing downloaded files."""

    def __init__(self, path: Path):
        """Create a new organizer for a given path."""
        self._path = path
        self._known_files: Set[Path] = set()
        # Keep the root dir
        self.mark(path)

    @property
    def path(self) -> Path:
        """Return the path for this organizer."""
        return self._path

    def resolve(self, target_file: Path) -> Path:
        """Resolve a file relative to the path of this organizer.

        Raises an exception if the file is outside the given directory.
        """
        return resolve_path(self.path, target_file)

    def accept_file(self, src: Path, dst: Path) -> None:
        """Move a file to this organizer and mark it."""
        src_absolute = src.resolve()
        dst_absolute = self.resolve(dst)

        if not src_absolute.exists():
            raise FileAcceptException("Source file does not exist")

        if not src_absolute.is_file():
            raise FileAcceptException("Source is a directory")

        logger.debug(f"Copying '{src_absolute}' to '{dst_absolute}")

        # Destination file is directory
        if dst_absolute.exists() and dst_absolute.is_dir():
            if prompt_yes_no(f"Overwrite folder {dst_absolute} with file?", default=False):
                shutil.rmtree(dst_absolute)
            else:
                logger.warn(f"Could not add file {dst_absolute}")
                return

        # Destination file exists
        if dst_absolute.exists() and dst_absolute.is_file():
            if filecmp.cmp(str(src_absolute), str(dst_absolute), shallow=False):
                pretty_logger.ignored_file(dst_absolute)

                # Bail out, nothing more to do
                self.mark(dst)
                return
            else:
                pretty_logger.modified_file(dst_absolute)
        else:
            pretty_logger.new_file(dst_absolute)

        # Create parent dir if needed
        dst_parent_dir: Path = dst_absolute.parent
        dst_parent_dir.mkdir(exist_ok=True, parents=True)

        # Move file
        shutil.move(str(src_absolute), str(dst_absolute))

        self.mark(dst)

    def mark(self, path: Path) -> None:
        """Mark a file as used so it will not get cleaned up."""
        absolute_path = self.path.joinpath(path).resolve()
        self._known_files.add(absolute_path)
        logger.debug(f"Tracked {absolute_path}")

    def cleanup(self) -> None:
        """Remove all untracked files in the organizer's dir."""
        logger.debug("Deleting all untracked files...")

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

    def _delete_file_if_confirmed(self, path: Path) -> None:
        prompt = f"Do you want to delete {path}"

        if prompt_yes_no(prompt, False):
            path.unlink()
