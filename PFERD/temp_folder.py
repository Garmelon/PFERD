"""Helper functions and classes for temporary folders."""

from typing import Optional, Type
from types import TracebackType

import pathlib
import shutil


class TempFolder():
    """A temporary folder that can create files or nested temp folders."""

    def __init__(self, path: pathlib.Path):
        """Create a new temporary folder for the given path."""
        self.counter = 0
        self.path = path

    def __str__(self) -> str:
        """Format the folder as a string."""
        return f"Folder at {self.path}"

    def __enter__(self) -> 'TempFolder':
        """Context manager entry function."""
        return self

    def __exit__(self,
                 type: Optional[Type[BaseException]],
                 value: Optional[BaseException],
                 traceback: Optional[TracebackType]) -> Optional[bool]:
        """Context manager exit function. Calls cleanup()."""
        self.cleanup()
        return None

    def new_file(self) -> pathlib.Path:
        """Return a unique path inside the folder, but don't create a file."""
        name = f"tmp-{self.__inc_and_get_counter():03}"
        return self.path.joinpath(name)

    def new_folder(self, prefix: str = "") -> 'TempFolder':
        """Create a new nested temporary folder and return its path."""
        name = f"{prefix if prefix else 'tmp'}-{self.__inc_and_get_counter():03}"

        sub_path = self.path.joinpath(name)
        sub_path.mkdir(parents=True)

        return TempFolder(sub_path)

    def cleanup(self) -> None:
        """Delete this folder and all contained files."""
        shutil.rmtree(self.path.absolute())

    def __inc_and_get_counter(self) -> int:
        """Get and increment the counter by one."""
        counter = self.counter
        self.counter += 1
        return counter
