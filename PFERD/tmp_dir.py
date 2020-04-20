"""Helper functions and classes for temporary folders."""

import logging
import shutil
from pathlib import Path
from types import TracebackType
from typing import Optional, Type

logger = logging.getLogger(__name__)


class TmpDir():
    """A temporary folder that can create files or nested temp folders."""

    def __init__(self, path: Path):
        """Create a new temporary folder for the given path."""
        self._counter = 0
        self._path = path

    def __str__(self) -> str:
        """Format the folder as a string."""
        return f"Folder at {self.path}"

    def __enter__(self) -> 'TmpDir':
        """Context manager entry function."""
        return self

    def __exit__(self,
                 type: Optional[Type[BaseException]],
                 value: Optional[BaseException],
                 traceback: Optional[TracebackType]) -> Optional[bool]:
        """Context manager exit function. Calls cleanup()."""
        self.cleanup()
        return None

    @property
    def path(self) -> Path:
        """Return the path of this folder."""
        return self._path

    def new_file(self, prefix: Optional[str] = None) -> Path:
        """Return a unique path inside the folder, but don't create a file."""
        name = f"{prefix if prefix else 'tmp'}-{self._inc_and_get_counter():03}"

        logger.debug(f"Creating temp file '{name}'")

        return self.path.joinpath(name)

    def new_folder(self, prefix: Optional[str] = None) -> 'TmpDir':
        """Create a new nested temporary folder and return its path."""
        name = f"{prefix if prefix else 'tmp'}-{self._inc_and_get_counter():03}"

        sub_path = self.path.joinpath(name)
        sub_path.mkdir(parents=True)

        logger.debug(f"Creating temp dir '{name}' at {sub_path}")

        return TmpDir(sub_path)

    def cleanup(self) -> None:
        """Delete this folder and all contained files."""
        logger.debug(f"Deleting temp folder {self.path}")

        shutil.rmtree(self.path.absolute())

    def _inc_and_get_counter(self) -> int:
        """Get and increment the counter by one."""
        counter = self._counter
        self._counter += 1
        return counter
