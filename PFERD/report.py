from dataclasses import dataclass
from pathlib import PurePath
from typing import Set


@dataclass
class MarkDuplicateException(Exception):
    """
    Tried to mark a file that was already marked.
    """

    path: PurePath


@dataclass
class MarkConflictException(Exception):
    """
    Marking the path would have caused a conflict.

    A conflict can have two reasons: Either the new file has the same path as
    the parent directory of a known file, or a parent directory of the new file
    has the same path as a known file. In either case, adding the new file
    would require a file and a directory to share the same path, which is
    usually not possible.
    """

    path: PurePath
    collides_with: PurePath


class Report:
    """
    A report of a synchronization. Includes all files found by the crawler, as
    well as the set of changes made to local files.
    """

    def __init__(self) -> None:
        self.known_files: Set[PurePath] = set()

        self.new_files: Set[PurePath] = set()
        self.changed_files: Set[PurePath] = set()
        self.deleted_files: Set[PurePath] = set()

    def mark(self, path: PurePath) -> None:
        """
        Mark a previously unknown file as known.

        May throw a MarkDuplicateException or a MarkConflictException. For more
        detail, see the respective exception's docstring.
        """

        for known_path in self.known_files:
            if path == known_path:
                raise MarkDuplicateException(path)

            if path.relative_to(known_path) or known_path.relative_to(path):
                raise MarkConflictException(path, known_path)

        self.known_files.add(path)

    def marked(self, path: PurePath) -> bool:
        return path in self.known_files

    def add_file(self, path: PurePath) -> None:
        """
        Unlike mark(), this function accepts any paths.
        """

        self.new_files.add(path)

    def change_file(self, path: PurePath) -> None:
        """
        Unlike mark(), this function accepts any paths.
        """

        self.changed_files.add(path)

    def delete_file(self, path: PurePath) -> None:
        """
        Unlike mark(), this function accepts any paths.
        """

        self.deleted_files.add(path)
