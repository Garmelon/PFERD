import json
from pathlib import Path, PurePath
from typing import Any, Dict, List, Set


class ReportLoadError(Exception):
    pass


class MarkDuplicateError(Exception):
    """
    Tried to mark a file that was already marked.
    """

    def __init__(self, path: PurePath):
        super().__init__(f"A previous file already used path {path}")
        self.path = path


class MarkConflictError(Exception):
    """
    Marking the path would have caused a conflict.

    A conflict can have two reasons: Either the new file has the same path as
    the parent directory of a known file, or a parent directory of the new file
    has the same path as a known file. In either case, adding the new file
    would require a file and a directory to share the same path, which is
    usually not possible.
    """

    def __init__(self, path: PurePath, collides_with: PurePath):
        super().__init__(f"File at {path} collides with previous file at {collides_with}")
        self.path = path
        self.collides_with = collides_with


# TODO Use PurePath.is_relative_to when updating to 3.9
def is_relative_to(a: PurePath, b: PurePath) -> bool:
    try:
        a.relative_to(b)
        return True
    except ValueError:
        return False


class Report:
    """
    A report of a synchronization. Includes all files found by the crawler, as
    well as the set of changes made to local files.
    """

    def __init__(self) -> None:
        self.reserved_files: Set[PurePath] = set()
        self.known_files: Set[PurePath] = set()

        self.added_files: Set[PurePath] = set()
        self.changed_files: Set[PurePath] = set()
        self.deleted_files: Set[PurePath] = set()

    @staticmethod
    def _get_list_of_strs(data: Dict[str, Any], key: str) -> List[str]:
        result: Any = data.get(key, [])

        if not isinstance(result, list):
            raise ReportLoadError(f"Incorrect format: {key!r} is not a list")

        for elem in result:
            if not isinstance(elem, str):
                raise ReportLoadError(f"Incorrect format: {key!r} must contain only strings")

        return result

    @classmethod
    def load(cls, path: Path) -> "Report":
        """
        May raise OSError, JsonDecodeError, ReportLoadError.
        """

        with open(path) as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ReportLoadError("Incorrect format: Root is not an object")

        self = cls()
        for elem in self._get_list_of_strs(data, "reserved"):
            self.mark_reserved(PurePath(elem))
        for elem in self._get_list_of_strs(data, "known"):
            self.mark(PurePath(elem))
        for elem in self._get_list_of_strs(data, "added"):
            self.add_file(PurePath(elem))
        for elem in self._get_list_of_strs(data, "changed"):
            self.change_file(PurePath(elem))
        for elem in self._get_list_of_strs(data, "deleted"):
            self.delete_file(PurePath(elem))

        return self

    def store(self, path: Path) -> None:
        """
        May raise OSError.
        """

        data = {
            "reserved": [str(path) for path in sorted(self.reserved_files)],
            "known": [str(path) for path in sorted(self.known_files)],
            "added": [str(path) for path in sorted(self.added_files)],
            "changed": [str(path) for path in sorted(self.changed_files)],
            "deleted": [str(path) for path in sorted(self.deleted_files)],
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")  # json.dump doesn't do this

    def mark_reserved(self, path: PurePath) -> None:
        self.reserved_files.add(path)

    def mark(self, path: PurePath) -> None:
        """
        Mark a previously unknown file as known.

        May throw a MarkDuplicateError or a MarkConflictError. For more detail,
        see the respective exception's docstring.
        """

        for other in self.marked:
            if path == other:
                raise MarkDuplicateError(path)

            if is_relative_to(path, other) or is_relative_to(other, path):
                raise MarkConflictError(path, other)

        self.known_files.add(path)

    @property
    def marked(self) -> Set[PurePath]:
        return self.known_files | self.reserved_files

    def is_marked(self, path: PurePath) -> bool:
        return path in self.marked

    def add_file(self, path: PurePath) -> None:
        """
        Unlike mark(), this function accepts any paths.
        """

        self.added_files.add(path)

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
