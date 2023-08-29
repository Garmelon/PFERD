from pathlib import PurePath
from typing import Iterator, Set

from .logging import log
from .utils import fmt_path


def name_variants(path: PurePath) -> Iterator[PurePath]:
    separator = " " if " " in path.stem else "_"
    i = 1
    while True:
        yield path.parent / f"{path.stem}{separator}{i}{path.suffix}"
        i += 1


class Deduplicator:
    FORBIDDEN_CHARS = '<>:"/\\|?*' + "".join([chr(i) for i in range(0, 32)])
    FORBIDDEN_NAMES = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }

    def __init__(self, windows_paths: bool) -> None:
        self._windows_paths = windows_paths

        self._known: Set[PurePath] = set()

    def _add(self, path: PurePath) -> None:
        self._known.add(path)

        # The last parent is just "."
        for parent in list(path.parents)[:-1]:
            self._known.add(parent)

    def _fixup_element(self, name: str) -> str:
        # For historical reasons, windows paths have some odd restrictions that
        # we're trying to avoid. See:
        # https://docs.microsoft.com/en-us/windows/win32/fileio/naming-a-file

        for char in self.FORBIDDEN_CHARS:
            name = name.replace(char, "_")

        path = PurePath(name)
        if path.stem in self.FORBIDDEN_NAMES:
            name = f"{path.stem}_{path.suffix}"

        if name.endswith(" ") or name.endswith("."):
            name += "_"

        return name

    def _fixup_for_windows(self, path: PurePath) -> PurePath:
        new_path = PurePath(*[self._fixup_element(elem) for elem in path.parts])
        if new_path != path:
            log.explain(f"Changed path to {fmt_path(new_path)} for windows compatibility")
        return new_path

    def fixup_path(self, path: PurePath) -> PurePath:
        """Fixes up the path for windows, if enabled. Returns the path unchanged otherwise."""
        if self._windows_paths:
            return self._fixup_for_windows(path)
        return path

    def mark(self, path: PurePath) -> PurePath:
        if self._windows_paths:
            path = self._fixup_for_windows(path)

        if path not in self._known:
            self._add(path)
            return path

        log.explain(f"Path {fmt_path(path)} is already taken, finding a new name")

        for variant in name_variants(path):
            if variant in self._known:
                log.explain(f"Path {fmt_path(variant)} is taken as well")
                continue

            log.explain(f"Found unused path {fmt_path(variant)}")
            self._add(variant)
            return variant

        # The "name_variants" iterator returns infinitely many paths
        raise RuntimeError("Unreachable")
