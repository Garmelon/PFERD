"""Helper functions and classes for temporary folders."""

import logging
import shutil
from pathlib import Path
from types import TracebackType
from typing import Optional, Type

from .utils import Location

LOGGER = logging.getLogger(__name__)


class TmpDir(Location):
    """A temporary folder that can create files or nested temp folders."""

    def __init__(self, path: Path):
        """Create a new temporary folder for the given path."""
        super().__init__(path)
        self._counter = 0
        self.cleanup()
        self.path.mkdir(parents=True, exist_ok=True)

    def __str__(self) -> str:
        """Format the folder as a string."""
        return f"Folder at {self.path}"

    def __enter__(self) -> 'TmpDir':
        """Context manager entry function."""
        return self

    # pylint: disable=useless-return
    def __exit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc_value: Optional[BaseException],
            traceback: Optional[TracebackType],
    ) -> Optional[bool]:
        """Context manager exit function. Calls cleanup()."""
        self.cleanup()
        return None

    def new_path(self, prefix: Optional[str] = None) -> Path:
        """
        Return a unique path inside the directory. Doesn't create a file or
        directory.
        """

        name = f"{prefix if prefix else 'tmp'}-{self._inc_and_get_counter():03}"

        LOGGER.debug("Creating temp file %s", name)

        return self.resolve(Path(name))

    def new_subdir(self, prefix: Optional[str] = None) -> 'TmpDir':
        """
        Create a new nested temporary folder and return it.
        """

        name = f"{prefix if prefix else 'tmp'}-{self._inc_and_get_counter():03}"
        sub_path = self.resolve(Path(name))
        sub_path.mkdir(parents=True)

        LOGGER.debug("Creating temp dir %s at %s", name, sub_path)

        return TmpDir(sub_path)

    def cleanup(self) -> None:
        """Delete this folder and all contained files."""
        LOGGER.debug("Deleting temp folder %s", self.path)

        shutil.rmtree(self.path.resolve())

    def _inc_and_get_counter(self) -> int:
        """Get and increment the counter by one."""
        counter = self._counter
        self._counter += 1
        return counter
