"""A simple helper for managing downloaded files.

A organizer is bound to a single directory.
"""

import logging
import shutil
from pathlib import Path
from typing import List, Set

from .utils import prompt_yes_no

logger = logging.getLogger(__name__)


class Organizer():
    """A helper for managing downloaded files."""

    def __init__(self, path: Path):
        """Create a new organizer for a given path."""
        self._path = path
        self._known_files: Set[Path] = set()

    @property
    def path(self) -> Path:
        """Return the path for this organizer."""
        return self._path

    # TODO: Name this method :/ move_from? add_file? new_file?
    def accept_file(self, source: Path, target: Path) -> None:
        """Move a file to this organizer and mark it."""
        source_absolute = self.path.joinpath(source).absolute()
        target_absolute = self.path.joinpath(target).absolute()

        logger.debug(f"Copying '{source_absolute}' to '{target_absolute}")

        shutil.move(str(source_absolute), str(target_absolute))

        self.mark_file(target)

    # TODO: Name this method :/ track_file?
    def mark_file(self, path: Path) -> None:
        """Mark a file as used so it will not get cleaned up."""
        absolute_path = self.path.joinpath(path).absolute()
        self._known_files.add(absolute_path)
        logger.debug(f"Tracked {absolute_path}")

    def resolve_file(self, file_path: Path) -> Path:
        """Resolve a file relative to the path of this organizer."""
        return self.path.joinpath(file_path)

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
                if path.absolute() not in self._known_files:
                    self._delete_file_if_confirmed(path)

        # Delete dir if it was empty and untracked
        dir_empty = len(list(start_dir.iterdir())) == 0
        if start_dir.absolute() not in self._known_files and dir_empty:
            start_dir.rmdir()

    def _delete_file_if_confirmed(self, path: Path) -> None:
        prompt = f"Do you want to delete {path}"

        if prompt_yes_no(prompt, False):
            path.unlink()
