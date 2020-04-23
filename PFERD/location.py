"""
Contains a Location class for objects with an inherent path.
"""

from pathlib import Path, PurePath


class ResolveException(Exception):
    """An exception while resolving a file."""
    # TODO take care of this when doing exception handling


class Location:
    """
    An object that has an inherent path.
    """

    def __init__(self, path: Path):
        self._path = path.resolve()

    @property
    def path(self) -> Path:
        """
        This object's location.
        """

        return self._path

    def resolve(self, target: PurePath) -> Path:
        """
        Resolve a file relative to the path of this location.

        Raises a [ResolveException] if the file is outside the given directory.
        """
        absolute_path = self.path.joinpath(target).resolve()

        # TODO Make this less inefficient
        if self.path not in absolute_path.parents:
            raise ResolveException(f"Path {target} is not inside directory {self.path}")

        return absolute_path
