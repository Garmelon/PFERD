import json
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Set


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


class Report:
    """
    A report of a synchronization. Includes all files found by the crawler, as
    well as the set of changes made to local files.
    """

    def __init__(self) -> None:
        # Paths found by the crawler, untransformed
        self.found_paths: Set[PurePath] = set()

        # Files reserved for metadata files (e. g. the report file or cookies)
        # that can't be overwritten by user transforms and won't be cleaned up
        # at the end.
        self.reserved_files: Set[PurePath] = set()

        # Files found by the crawler, transformed. Only includes files that
        # were downloaded (or a download was attempted)
        self.known_files: Set[PurePath] = set()

        self.added_files: Set[PurePath] = set()
        self.changed_files: Set[PurePath] = set()
        self.deleted_files: Set[PurePath] = set()
        # Files that should have been deleted by the cleanup but weren't
        self.not_deleted_files: Set[PurePath] = set()

        # Custom crawler-specific data
        self.custom: Dict[str, Any] = dict()

        # Encountered errors and warnings
        self.encountered_warnings: List[str] = []
        self.encountered_errors: List[str] = []

    @staticmethod
    def _get_list_of_strs(data: Dict[str, Any], key: str) -> List[str]:
        result: Any = data.get(key, [])

        if not isinstance(result, list):
            raise ReportLoadError(f"Incorrect format: {key!r} is not a list")

        for elem in result:
            if not isinstance(elem, str):
                raise ReportLoadError(f"Incorrect format: {key!r} must contain only strings")

        return result

    @staticmethod
    def _get_str_dictionary(data: Dict[str, Any], key: str) -> Dict[str, Any]:
        result: Dict[str, Any] = data.get(key, {})

        if not isinstance(result, dict):
            raise ReportLoadError(f"Incorrect format: {key!r} is not a dictionary")

        return result

    @classmethod
    def load(cls, path: Path) -> "Report":
        """
        May raise OSError, UnicodeDecodeError, JsonDecodeError, ReportLoadError.
        """

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ReportLoadError("Incorrect format: Root is not an object")

        self = cls()
        for elem in self._get_list_of_strs(data, "found"):
            self.found(PurePath(elem))
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
        for elem in self._get_list_of_strs(data, "not_deleted"):
            self.not_delete_file(PurePath(elem))
        self.custom = self._get_str_dictionary(data, "custom")
        self.encountered_errors = self._get_list_of_strs(data, "encountered_errors")
        self.encountered_warnings = self._get_list_of_strs(data, "encountered_warnings")

        return self

    def store(self, path: Path) -> None:
        """
        May raise OSError.
        """

        data = {
            "found": [str(path) for path in sorted(self.found_paths)],
            "reserved": [str(path) for path in sorted(self.reserved_files)],
            "known": [str(path) for path in sorted(self.known_files)],
            "added": [str(path) for path in sorted(self.added_files)],
            "changed": [str(path) for path in sorted(self.changed_files)],
            "deleted": [str(path) for path in sorted(self.deleted_files)],
            "not_deleted": [str(path) for path in sorted(self.not_deleted_files)],
            "custom": self.custom,
            "encountered_warnings": self.encountered_warnings,
            "encountered_errors": self.encountered_errors,
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")  # json.dump doesn't do this

    def found(self, path: PurePath) -> None:
        self.found_paths.add(path)

    def mark_reserved(self, path: PurePath) -> None:
        if path in self.marked:
            raise RuntimeError("Trying to reserve an already reserved file")

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

            if path.is_relative_to(other) or other.is_relative_to(path):
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

    def not_delete_file(self, path: PurePath) -> None:
        """
        Unlike mark(), this function accepts any paths.
        """

        self.not_deleted_files.add(path)

    def add_custom_value(self, key: str, value: Any) -> None:
        """
        Adds a custom value under the passed key, overwriting any existing
        """
        self.custom[key] = value

    def get_custom_value(self, key: str) -> Optional[Any]:
        """
        Retrieves a custom value for the given key.
        """
        return self.custom.get(key)

    def add_error(self, error: str) -> None:
        """
        Adds an error to this report's error list.
        """
        self.encountered_errors.append(error)

    def add_warning(self, warning: str) -> None:
        """
        Adds a warning to this report's warning list.
        """
        self.encountered_warnings.append(warning)
