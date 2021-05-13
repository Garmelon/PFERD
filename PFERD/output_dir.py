import filecmp
import os
import random
import shutil
import string
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path, PurePath
# TODO In Python 3.9 and above, AsyncContextManager is deprecated
from typing import AsyncContextManager, AsyncIterator, BinaryIO, Optional

from rich.markup import escape

from .conductor import TerminalConductor
from .report import MarkConflictException, MarkDuplicateException, Report
from .utils import prompt_yes_no

SUFFIX_CHARS = string.ascii_lowercase + string.digits
SUFFIX_LENGTH = 6
TRIES = 5


class OutputDirException(Exception):
    pass


class Redownload(Enum):
    NEVER = "never"
    NEVER_SMART = "never-smart"
    ALWAYS = "always"
    ALWAYS_SMART = "always-smart"


class OnConflict(Enum):
    PROMPT = "prompt"
    LOCAL_FIRST = "local-first"
    REMOTE_FIRST = "remote-first"
    NO_DELETE = "no-delete"


@dataclass
class Heuristics:
    mtime: Optional[datetime]


class FileSink:
    def __init__(self, file: BinaryIO):
        self._file = file
        self._done = False

    @property
    def file(self) -> BinaryIO:
        return self._file

    def done(self) -> None:
        self._done = True

    def is_done(self) -> bool:
        return self._done


@dataclass
class DownloadInfo:
    path: PurePath
    local_path: Path
    tmp_path: Path
    heuristics: Heuristics
    on_conflict: OnConflict
    success: bool = False


class OutputDirectory:
    def __init__(
            self,
            root: Path,
            redownload: Redownload,
            on_conflict: OnConflict,
            conductor: TerminalConductor,
    ):
        self._root = root
        self._redownload = redownload
        self._on_conflict = on_conflict
        self._conductor = conductor

        self._report = Report()

    def _mark(self, path: PurePath) -> None:
        """
        May throw an OutputDirException
        """

        try:
            self._report.mark(path)
        except MarkDuplicateException:
            msg = "Another file has already been placed here."
            raise OutputDirException(msg)
        except MarkConflictException as e:
            msg = f"Collides with other file: {e.collides_with}"
            raise OutputDirException(msg)

    def _resolve(self, path: PurePath) -> Path:
        """
        May throw an OutputDirException.
        """

        if ".." in path.parts:
            msg = f"Path {path} contains forbidden '..'"
            raise OutputDirException(msg)
        return self._root / path

    def _should_download(
            self,
            local_path: Path,
            heuristics: Heuristics,
            redownload: Redownload,
    ) -> bool:
        # If we don't have a *file* at the local path, we'll always redownload
        # since we know that the remote is different from the local files. This
        # includes the case where no local file exists.
        if not local_path.is_file():
            return True

        if redownload == Redownload.NEVER:
            return False
        elif redownload == Redownload.ALWAYS:
            return True

        stat = local_path.stat()

        remote_newer = None
        if mtime := heuristics.mtime:
            remote_newer = mtime.timestamp() > stat.st_mtime

        if redownload == Redownload.NEVER_SMART:
            if remote_newer is None:
                return False
            else:
                return remote_newer
        elif redownload == Redownload.ALWAYS_SMART:
            if remote_newer is None:
                return True
            else:
                return not remote_newer

        # This should never be reached
        raise ValueError(f"{redownload!r} is not a valid redownload policy")

    # The following conflict resolution functions all return False if the local
    # file(s) should be kept and True if they should be replaced by the remote
    # files.

    async def _conflict_lfrf(
            self,
            on_conflict: OnConflict,
            path: PurePath,
    ) -> bool:
        if on_conflict == OnConflict.PROMPT:
            async with self._conductor.exclusive_output():
                prompt = f"Replace {path} with remote file?"
                return await prompt_yes_no(prompt, default=False)
        elif on_conflict == OnConflict.LOCAL_FIRST:
            return False
        elif on_conflict == OnConflict.REMOTE_FIRST:
            return True
        elif on_conflict == OnConflict.NO_DELETE:
            return True

        # This should never be reached
        raise ValueError(f"{on_conflict!r} is not a valid conflict policy")

    async def _conflict_ldrf(
            self,
            on_conflict: OnConflict,
            path: PurePath,
    ) -> bool:
        if on_conflict == OnConflict.PROMPT:
            async with self._conductor.exclusive_output():
                prompt = f"Recursively delete {path} and replace with remote file?"
                return await prompt_yes_no(prompt, default=False)
        elif on_conflict == OnConflict.LOCAL_FIRST:
            return False
        elif on_conflict == OnConflict.REMOTE_FIRST:
            return True
        elif on_conflict == OnConflict.NO_DELETE:
            return False

        # This should never be reached
        raise ValueError(f"{on_conflict!r} is not a valid conflict policy")

    async def _conflict_lfrd(
            self,
            on_conflict: OnConflict,
            path: PurePath,
            parent: PurePath,
    ) -> bool:
        if on_conflict == OnConflict.PROMPT:
            async with self._conductor.exclusive_output():
                prompt = f"Delete {parent} so remote file {path} can be downloaded?"
                return await prompt_yes_no(prompt, default=False)
        elif on_conflict == OnConflict.LOCAL_FIRST:
            return False
        elif on_conflict == OnConflict.REMOTE_FIRST:
            return True
        elif on_conflict == OnConflict.NO_DELETE:
            return False

        # This should never be reached
        raise ValueError(f"{on_conflict!r} is not a valid conflict policy")

    async def _conflict_delete_lf(
            self,
            on_conflict: OnConflict,
            path: PurePath,
    ) -> bool:
        if on_conflict == OnConflict.PROMPT:
            async with self._conductor.exclusive_output():
                prompt = f"Delete {path}?"
                return await prompt_yes_no(prompt, default=False)
        elif on_conflict == OnConflict.LOCAL_FIRST:
            return False
        elif on_conflict == OnConflict.REMOTE_FIRST:
            return True
        elif on_conflict == OnConflict.NO_DELETE:
            return False

        # This should never be reached
        raise ValueError(f"{on_conflict!r} is not a valid conflict policy")

    def _tmp_path(self, base: Path, suffix_length: int) -> Path:
        prefix = "" if base.name.startswith(".") else "."
        suffix = "".join(random.choices(SUFFIX_CHARS, k=suffix_length))
        name = f"{prefix}{base.name}.tmp.{suffix}"
        return base.parent / name

    @asynccontextmanager
    async def _sink_context_manager(
            self,
            file: BinaryIO,
            info: DownloadInfo,
    ) -> AsyncIterator[FileSink]:
        sink = FileSink(file)
        try:
            with file:
                yield sink
        finally:
            info.success = sink.is_done()
            await self._after_download(info)

    async def download(
            self,
            path: PurePath,
            mtime: Optional[datetime] = None,
            redownload: Optional[Redownload] = None,
            on_conflict: Optional[OnConflict] = None,
    ) -> Optional[AsyncContextManager[FileSink]]:
        """
        May throw an OutputDirException.
        """

        heuristics = Heuristics(mtime)
        redownload = self._redownload if redownload is None else redownload
        on_conflict = self._on_conflict if on_conflict is None else on_conflict
        local_path = self._resolve(path)

        self._mark(path)

        if not self._should_download(local_path, heuristics, redownload):
            return None

        # Detect and solve local-dir-remote-file conflict
        if local_path.is_dir():
            if await self._conflict_ldrf(on_conflict, path):
                shutil.rmtree(local_path)
            else:
                return None

        # Detect and solve local-file-remote-dir conflict
        for parent in path.parents:
            local_parent = self._resolve(parent)
            if local_parent.exists() and not local_parent.is_dir():
                if await self._conflict_lfrd(on_conflict, path, parent):
                    local_parent.unlink()
                    break
                else:
                    return None

        # Ensure parent directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # Create tmp file
        for attempt in range(TRIES):
            suffix_length = SUFFIX_LENGTH + 2 * attempt
            tmp_path = self._tmp_path(local_path, suffix_length)
            info = DownloadInfo(path, local_path, tmp_path,
                                heuristics, on_conflict)
            try:
                file = open(tmp_path, "xb")
                return self._sink_context_manager(file, info)
            except FileExistsError:
                pass  # Try again

        return None

    async def _after_download(self, info: DownloadInfo) -> None:
        changed = False

        if not info.success:
            info.tmp_path.unlink()
            return

        # Solve conflicts arising from existing local file
        if info.local_path.exists():
            changed = True
            if filecmp.cmp(info.local_path, info.tmp_path):
                info.tmp_path.unlink()
                return

            if not await self._conflict_lfrf(info.on_conflict, info.path):
                info.tmp_path.unlink()
                return

        # Modify metadata if necessary
        if mtime := info.heuristics.mtime:
            # TODO Pick an implementation
            # Rounding up to avoid inaccuracies in how the OS stores timestamps
            # mtimestamp = math.ceil(mtime.timestamp())
            mtimestamp = mtime.timestamp()
            os.utime(info.tmp_path, times=(mtimestamp, mtimestamp))

        info.tmp_path.replace(info.local_path)

        if changed:
            self._conductor.print(
                f"[bold bright_yellow]Changed[/] {escape(str(info.path))}")
            self._report.change_file(info.path)
        else:
            self._conductor.print(
                f"[bold bright_green]Added[/] {escape(str(info.path))}")
            self._report.add_file(info.path)

    async def cleanup(self) -> None:
        await self._cleanup_dir(self._root, PurePath())

    async def _cleanup(self, path: Path, pure: PurePath) -> None:
        if path.is_dir():
            await self._cleanup_dir(path, pure)
        elif path.is_file():
            await self._cleanup_file(path, pure)

    async def _cleanup_dir(self, path: Path, pure: PurePath) -> None:
        for child in path.iterdir():
            pure_child = pure / child.name
            await self._cleanup(child, pure_child)

        try:
            path.rmdir()
        except OSError:
            pass

    async def _cleanup_file(self, path: Path, pure: PurePath) -> None:
        if self._report.marked(pure):
            return

        if await self._conflict_delete_lf(self._on_conflict, pure):
            try:
                path.unlink()
                self._conductor.print(
                    f"[bold bright_magenta]Deleted[/] {escape(str(path))}")
                self._report.delete_file(pure)
            except OSError:
                pass
