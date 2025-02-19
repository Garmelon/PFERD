import filecmp
import json
import os
import random
import shutil
import string
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path, PurePath
from typing import BinaryIO, Iterator, Optional, Tuple

from .logging import log
from .report import Report, ReportLoadError
from .utils import ReusableAsyncContextManager, fmt_path, fmt_real_path, prompt_yes_no

SUFFIX_CHARS = string.ascii_lowercase + string.digits
SUFFIX_LENGTH = 6
TRIES = 5


class OutputDirError(Exception):
    pass


class Redownload(Enum):
    NEVER = "never"
    NEVER_SMART = "never-smart"
    ALWAYS = "always"
    ALWAYS_SMART = "always-smart"

    @staticmethod
    def from_string(string: str) -> "Redownload":
        try:
            return Redownload(string)
        except ValueError:
            raise ValueError("must be one of 'never', 'never-smart',"
                             " 'always', 'always-smart'")


class OnConflict(Enum):
    PROMPT = "prompt"
    LOCAL_FIRST = "local-first"
    REMOTE_FIRST = "remote-first"
    NO_DELETE = "no-delete"
    NO_DELETE_PROMPT_OVERWRITE = "no-delete-prompt-overwrite"

    @staticmethod
    def from_string(string: str) -> "OnConflict":
        try:
            return OnConflict(string)
        except ValueError:
            raise ValueError("must be one of 'prompt', 'local-first',"
                             " 'remote-first', 'no-delete', 'no-delete-prompt-overwrite'")


@dataclass
class Heuristics:
    etag_differs: Optional[bool]
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
    remote_path: PurePath
    path: PurePath
    local_path: Path
    tmp_path: Path
    heuristics: Heuristics
    on_conflict: OnConflict
    success: bool = False


class FileSinkToken(ReusableAsyncContextManager[FileSink]):
    # Whenever this class is entered, it creates a new temporary file and
    # returns a corresponding FileSink.
    #
    # When it is exited again, the file is closed and information about the
    # download handed back to the OutputDirectory.

    def __init__(
            self,
            output_dir: "OutputDirectory",
            remote_path: PurePath,
            path: PurePath,
            local_path: Path,
            heuristics: Heuristics,
            on_conflict: OnConflict,
    ):
        super().__init__()

        self._output_dir = output_dir
        self._remote_path = remote_path
        self._path = path
        self._local_path = local_path
        self._heuristics = heuristics
        self._on_conflict = on_conflict

    async def _on_aenter(self) -> FileSink:
        tmp_path, file = await self._output_dir._create_tmp_file(self._local_path)
        sink = FileSink(file)

        async def after_download() -> None:
            await self._output_dir._after_download(DownloadInfo(
                self._remote_path,
                self._path,
                self._local_path,
                tmp_path,
                self._heuristics,
                self._on_conflict,
                sink.is_done(),
            ))

        self._stack.push_async_callback(after_download)
        self._stack.enter_context(file)

        return sink


class OutputDirectory:
    REPORT_FILE = PurePath(".report")

    def __init__(
            self,
            root: Path,
            redownload: Redownload,
            on_conflict: OnConflict,
    ):
        if os.name == "nt":
            # Windows limits the path length to 260 for some historical reason.
            # If you want longer paths, you will have to add the "\\?\" prefix
            # in front of your path. See:
            # https://docs.microsoft.com/en-us/windows/win32/fileio/naming-a-file#maximum-path-length-limitation
            self._root = Path("\\\\?\\" + str(root.absolute()))
        else:
            self._root = root

        self._redownload = redownload
        self._on_conflict = on_conflict

        self._report_path = self.resolve(self.REPORT_FILE)
        self._report = Report()
        self._prev_report: Optional[Report] = None

        self.register_reserved(self.REPORT_FILE)

    @property
    def report(self) -> Report:
        return self._report

    @property
    def prev_report(self) -> Optional[Report]:
        return self._prev_report

    def prepare(self) -> None:
        log.explain_topic(f"Creating base directory at {fmt_real_path(self._root)}")

        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise OutputDirError("Failed to create base directory")

    def register_reserved(self, path: PurePath) -> None:
        self._report.mark_reserved(path)

    def resolve(self, path: PurePath) -> Path:
        """
        May throw an OutputDirError.
        """

        if ".." in path.parts:
            raise OutputDirError(f"Forbidden segment '..' in path {fmt_path(path)}")
        if "." in path.parts:
            raise OutputDirError(f"Forbidden segment '.' in path {fmt_path(path)}")

        return self._root / path

    def _should_download(
            self,
            local_path: Path,
            heuristics: Heuristics,
            redownload: Redownload,
            on_conflict: OnConflict,
    ) -> bool:
        if not local_path.exists():
            log.explain("No corresponding file present locally")
            return True

        if on_conflict == OnConflict.LOCAL_FIRST:
            # Whatever is here, it will never be overwritten, so we don't need
            # to download the file.
            log.explain("Conflict resolution is 'local-first' and path exists")
            return False

        if not local_path.is_file():
            # We know that there is *something* here that's not a file.
            log.explain("Non-file (probably a directory) present locally")

            # If on_conflict is LOCAL_FIRST or NO_DELETE, we know that it would
            # never be overwritten. It also doesn't have any relevant stats to
            # update. This means that we don't have to download the file
            # because we'd just always throw it away again.
            if on_conflict in {OnConflict.LOCAL_FIRST, OnConflict.NO_DELETE}:
                log.explain(f"Conflict resolution is {on_conflict.value!r}")
                return False

            return True

        log.explain(f"Redownload policy is {redownload.value}")

        if redownload == Redownload.NEVER:
            return False
        elif redownload == Redownload.ALWAYS:
            return True

        stat = local_path.stat()

        remote_newer = None

        # ETag should be a more reliable indicator than mtime, so we check it first
        if heuristics.etag_differs is not None:
            remote_newer = heuristics.etag_differs
            if remote_newer:
                log.explain("Remote file's entity tag differs")
            else:
                log.explain("Remote file's entity tag is the same")

        # Python on Windows crashes when faced with timestamps around the unix epoch
        if remote_newer is None and heuristics.mtime and (os.name != "nt" or heuristics.mtime.year > 1970):
            mtime = heuristics.mtime
            remote_newer = mtime.timestamp() > stat.st_mtime
            if remote_newer:
                log.explain("Remote file seems to be newer")
            else:
                log.explain("Remote file doesn't seem to be newer")

        if redownload == Redownload.NEVER_SMART:
            if remote_newer is None:
                return False
            else:
                return remote_newer
        elif redownload == Redownload.ALWAYS_SMART:
            if remote_newer is None:
                return True
            else:
                return remote_newer

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
        if on_conflict in {OnConflict.PROMPT, OnConflict.NO_DELETE_PROMPT_OVERWRITE}:
            async with log.exclusive_output():
                prompt = f"Replace {fmt_path(path)} with remote file?"
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
        if on_conflict in {OnConflict.PROMPT, OnConflict.NO_DELETE_PROMPT_OVERWRITE}:
            async with log.exclusive_output():
                prompt = f"Recursively delete {fmt_path(path)} and replace with remote file?"
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
        if on_conflict in {OnConflict.PROMPT, OnConflict.NO_DELETE_PROMPT_OVERWRITE}:
            async with log.exclusive_output():
                prompt = f"Delete {fmt_path(parent)} so remote file {fmt_path(path)} can be downloaded?"
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
            async with log.exclusive_output():
                prompt = f"Delete {fmt_path(path)}?"
                return await prompt_yes_no(prompt, default=False)
        elif on_conflict == OnConflict.LOCAL_FIRST:
            return False
        elif on_conflict == OnConflict.REMOTE_FIRST:
            return True
        elif on_conflict in {OnConflict.NO_DELETE, OnConflict.NO_DELETE_PROMPT_OVERWRITE}:
            return False

        # This should never be reached
        raise ValueError(f"{on_conflict!r} is not a valid conflict policy")

    def _tmp_path(self, base: Path, suffix_length: int) -> Path:
        prefix = "" if base.name.startswith(".") else "."
        suffix = "".join(random.choices(SUFFIX_CHARS, k=suffix_length))
        name = f"{prefix}{base.name}.tmp.{suffix}"
        return base.parent / name

    async def _create_tmp_file(
            self,
            local_path: Path,
    ) -> Tuple[Path, BinaryIO]:
        """
        May raise an OutputDirError.
        """

        # Create tmp file
        for attempt in range(TRIES):
            suffix_length = SUFFIX_LENGTH + 2 * attempt
            tmp_path = self._tmp_path(local_path, suffix_length)
            try:
                return tmp_path, open(tmp_path, "xb")
            except FileExistsError:
                pass  # Try again

        raise OutputDirError("Failed to create temporary file")

    def should_try_download(
        self,
        path: PurePath,
        *,
        etag_differs: Optional[bool] = None,
        mtime: Optional[datetime] = None,
        redownload: Optional[Redownload] = None,
        on_conflict: Optional[OnConflict] = None,
    ) -> bool:
        heuristics = Heuristics(etag_differs, mtime)
        redownload = self._redownload if redownload is None else redownload
        on_conflict = self._on_conflict if on_conflict is None else on_conflict
        local_path = self.resolve(path)

        return self._should_download(local_path, heuristics, redownload, on_conflict)

    async def download(
            self,
            remote_path: PurePath,
            path: PurePath,
            *,
            etag_differs: Optional[bool] = None,
            mtime: Optional[datetime] = None,
            redownload: Optional[Redownload] = None,
            on_conflict: Optional[OnConflict] = None,
    ) -> Optional[FileSinkToken]:
        """
        May throw an OutputDirError, a MarkDuplicateError or a
        MarkConflictError.
        """

        heuristics = Heuristics(etag_differs, mtime)
        redownload = self._redownload if redownload is None else redownload
        on_conflict = self._on_conflict if on_conflict is None else on_conflict
        local_path = self.resolve(path)

        self._report.mark(path)

        if not self._should_download(local_path, heuristics, redownload, on_conflict):
            return None

        # Detect and solve local-dir-remote-file conflict
        if local_path.is_dir():
            log.explain("Conflict: There's a directory in place of the local file")
            if await self._conflict_ldrf(on_conflict, path):
                log.explain("Result: Delete the obstructing directory")
                shutil.rmtree(local_path)
            else:
                log.explain("Result: Keep the obstructing directory")
                return None

        # Detect and solve local-file-remote-dir conflict
        for parent in path.parents:
            local_parent = self.resolve(parent)
            if local_parent.exists() and not local_parent.is_dir():
                log.explain("Conflict: One of the local file's parents is a file")
                if await self._conflict_lfrd(on_conflict, path, parent):
                    log.explain("Result: Delete the obstructing file")
                    local_parent.unlink()
                    break
                else:
                    log.explain("Result: Keep the obstructing file")
                    return None

        # Ensure parent directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)

        return FileSinkToken(self, remote_path, path, local_path, heuristics, on_conflict)

    def _update_metadata(self, info: DownloadInfo) -> None:
        if mtime := info.heuristics.mtime:
            mtimestamp = mtime.timestamp()
            os.utime(info.local_path, times=(mtimestamp, mtimestamp))

    @contextmanager
    def _ensure_deleted(self, path: Path) -> Iterator[None]:
        try:
            yield
        finally:
            path.unlink(missing_ok=True)

    async def _after_download(self, info: DownloadInfo) -> None:
        with self._ensure_deleted(info.tmp_path):
            log.status("[bold cyan]", "Downloaded", fmt_path(info.remote_path))
            log.explain_topic(f"Processing downloaded file for {fmt_path(info.path)}")

            changed = False

            if not info.success:
                log.explain("Download unsuccessful, aborting")
                return

            # Solve conflicts arising from existing local file
            if info.local_path.exists():
                changed = True

                if filecmp.cmp(info.local_path, info.tmp_path):
                    log.explain("Contents identical with existing file")
                    log.explain("Updating metadata of existing file")
                    self._update_metadata(info)
                    return

                log.explain("Conflict: The local and remote versions differ")
                if await self._conflict_lfrf(info.on_conflict, info.path):
                    log.explain("Result: Replacing local with remote version")
                else:
                    log.explain("Result: Keeping local version")
                    return

            info.tmp_path.replace(info.local_path)
            log.explain("Updating file metadata")
            self._update_metadata(info)

            if changed:
                log.status("[bold bright_yellow]", "Changed", fmt_path(info.path))
                self._report.change_file(info.path)
            else:
                log.status("[bold bright_green]", "Added", fmt_path(info.path))
                self._report.add_file(info.path)

    async def cleanup(self) -> None:
        await self._cleanup_dir(self._root, PurePath(), delete_self=False)

    async def _cleanup(self, path: Path, pure: PurePath) -> None:
        if path.is_dir():
            await self._cleanup_dir(path, pure)
        elif path.is_file():
            await self._cleanup_file(path, pure)

    async def _cleanup_dir(self, path: Path, pure: PurePath, delete_self: bool = True) -> None:
        for child in sorted(path.iterdir()):
            pure_child = pure / child.name
            await self._cleanup(child, pure_child)

        if delete_self:
            try:
                path.rmdir()
            except OSError:
                pass

    async def _cleanup_file(self, path: Path, pure: PurePath) -> None:
        if self._report.is_marked(pure):
            return

        if await self._conflict_delete_lf(self._on_conflict, pure):
            try:
                path.unlink()
                log.status("[bold bright_magenta]", "Deleted", fmt_path(pure))
                self._report.delete_file(pure)
            except OSError:
                pass
        else:
            log.not_deleted("[bold bright_magenta]", "Not deleted", fmt_path(pure))
            self._report.not_delete_file(pure)

    def load_prev_report(self) -> None:
        log.explain_topic(f"Loading previous report from {fmt_real_path(self._report_path)}")
        try:
            self._prev_report = Report.load(self._report_path)
            log.explain("Loaded report successfully")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ReportLoadError) as e:
            log.explain("Failed to load report")
            log.explain(str(e))

    def store_report(self) -> None:
        log.explain_topic(f"Storing report to {fmt_real_path(self._report_path)}")
        try:
            self._report.store(self._report_path)
            log.explain("Stored report successfully")
        except OSError as e:
            log.warn(f"Failed to save report to {fmt_real_path(self._report_path)}")
            log.warn_contd(str(e))
