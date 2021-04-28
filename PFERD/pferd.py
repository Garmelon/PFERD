"""
Convenience functions for using PFERD.
"""

import logging
from pathlib import Path
from typing import List, Optional, Union
import asyncio

from .authenticators import UserPassAuthenticator
from .diva import (
    DivaDownloader,
    DivaDownloadStrategy,
    DivaPlaylistCrawler,
    diva_download_new,
)
from .download_summary import DownloadSummary
from .errors import FatalException, swallow_and_print_errors
from .ilias import (
    IliasDirectoryFilter,
    IliasDownloader,
    IliasDownloadInfo,
    IliasDownloadStrategy,
    KitShibbolethAuthenticator,
    download_modified_or_new,
    IliasSycronizer,
    ResultContainer,
)
from .ipd import (
    IpdCrawler,
    IpdDownloader,
    IpdDownloadInfo,
    IpdDownloadStrategy,
    ipd_download_new_or_modified,
)
from .location import Location
from .logging import PrettyLogger, enable_logging
from .organizer import FileConflictResolver, Organizer, resolve_prompt_user
from .tmp_dir import TmpDir
from .transform import TF, Transform, apply_transform
from .utils import PathLike, to_path

# TODO save known-good cookies as soon as possible


LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


class IliasTarget:
    """
    Used to store associated options for a crawl target and hold the a reference to the results container
    """

    def __init__(
        self,
        results: ResultContainer,
        target: PathLike,
        transform: Transform = lambda x: x,
        download_strategy: IliasDownloadStrategy = download_modified_or_new,
        clean: bool = True,
        timeout: int = 5,
        file_conflict_resolver: FileConflictResolver = resolve_prompt_user,
    ):
        self.results = results
        self.target = target
        self.transform = transform
        self.download_strategy = download_strategy
        self.clean = clean
        self.timeout = timeout
        self.file_conflict_resolver = file_conflict_resolver

    def get_results(self) -> List[IliasDownloadInfo]:
        """
        Returns the results of the associated crawl target
        """
        return self.results.get_results()


class Pferd(Location):
    # pylint: disable=too-many-arguments
    """
    The main entrypoint in your Pferd usage: This class combines a number of
    useful shortcuts for running synchronizers in a single interface.
    """

    def __init__(
        self, base_dir: Path, tmp_dir: Path = Path(".tmp"), test_run: bool = False
    ):
        super().__init__(Path(base_dir))

        self._download_summary = DownloadSummary()
        self._tmp_dir = TmpDir(self.resolve(tmp_dir))
        self._test_run = test_run
        self._ilias_targets: List[IliasTarget] = []

    @staticmethod
    def enable_logging() -> None:
        """
        Enable and configure logging via the logging module.
        """

        enable_logging()

    @staticmethod
    def _print_transformables(transformables: List[TF]) -> None:
        LOGGER.info("")
        LOGGER.info("Results of the test run:")
        for transformable in transformables:
            LOGGER.info(transformable.path)

    @staticmethod
    def _get_authenticator(
        username: Optional[str], password: Optional[str]
    ) -> KitShibbolethAuthenticator:
        inner_auth = UserPassAuthenticator(
            "ILIAS - Pferd.py", username, password)
        return KitShibbolethAuthenticator(inner_auth)

    @swallow_and_print_errors
    def ilias_kit(
        self,
        dir_filter: IliasDirectoryFilter = lambda x, y: True,
        cookies: Optional[PathLike] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> IliasSycronizer:
        """
        Create a ILIAS Sycronizer for the ILIAS instance of the KIT.

        Keyword Arguments:
            dir_filter {IliasDirectoryFilter} -- A filter for directories. Will be applied on the
                crawler level, these directories and all of their content is skipped.
                (default: {lambdax:True})
            cookies {Optional[Path]} -- The path to store and load cookies from.
                (default: {None})
            username {Optional[str]} -- The SCC username. If none is given, it will prompt
                the user. (default: {None})
            password {Optional[str]} -- The SCC password. If none is given, it will prompt
                the user. (default: {None})
        """

        # This authenticator only works with the KIT ilias instance.
        authenticator = Pferd._get_authenticator(
            username=username, password=password)
        return IliasSycronizer(
            "https://ilias.studium.kit.edu/", authenticator, cookies, dir_filter
        )

    def add_ilias_personal_desktop(
        self,
        ilias: IliasSycronizer,
        target: PathLike,
        transform: Transform = lambda x: x,
        download_strategy: IliasDownloadStrategy = download_modified_or_new,
        clean: bool = True,
        timeout: int = 5,
        file_conflict_resolver: FileConflictResolver = resolve_prompt_user,
    ):
        """
        Add the ILIAS "personal desktop" as a crawl target.
        Arguments:
            ilias {IliasSycronizer} -- the ILIAS Instance
            target {Path} -- the target path to write the data to
        Keyword Arguments:
            transform {Transform} -- A transformation function for the output paths. Return None
                to ignore a file. (default: {lambdax:x})
            download_strategy {DownloadStrategy} -- A function to determine which files need to
                be downloaded. Can save bandwidth and reduce the number of requests.
                (default: {download_modified_or_new})
            clean {bool} -- Whether to clean up when the method finishes.
            timeout {int} -- The download timeout for opencast videos. Sadly needed due to a
                requests bug.
            file_conflict_resolver {FileConflictResolver} -- A function specifying how to deal
                with overwriting or deleting files. The default always asks the user.
        """
        results = ilias.add_target(
            lambda crawler: crawler.crawl_personal_desktop(),
        )
        target = IliasTarget(
            results,
            target,
            transform,
            download_strategy,
            clean,
            timeout,
            file_conflict_resolver,
        )
        self._ilias_targets.append(target)

    def add_ilias_folder(
        self,
        ilias: IliasSycronizer,
        target: PathLike,
        course_id: str,
        transform: Transform = lambda x: x,
        download_strategy: IliasDownloadStrategy = download_modified_or_new,
        clean: bool = True,
        timeout: int = 5,
        file_conflict_resolver: FileConflictResolver = resolve_prompt_user,
    ):
        """
        Add a course to syncronize

        Arguments:
            ilias {IliasSycronizer} -- the ILIAS Instance
            target {Path} -- the target path to write the data to
            course_id {str} -- the id of the main course page (found in the URL after ref_id
                when opening the course homepage)
        Keyword Arguments:
            transform {Transform} -- A transformation function for the output paths. Return None
                to ignore a file. (default: {lambdax:x})
            download_strategy {DownloadStrategy} -- A function to determine which files need to
                be downloaded. Can save bandwidth and reduce the number of requests.
                (default: {download_modified_or_new})
            clean {bool} -- Whether to clean up when the method finishes.
            timeout {int} -- The download timeout for opencast videos. Sadly needed due to a
                requests bug.
            file_conflict_resolver {FileConflictResolver} -- A function specifying how to deal
                with overwriting or deleting files. The default always asks the user.
        """

        results = ilias.add_target(
            lambda crawler: crawler.crawl_course(course_id),
        )
        target = IliasTarget(
            results,
            target,
            transform,
            download_strategy,
            clean,
            timeout,
            file_conflict_resolver,
        )
        self._ilias_targets.append(target)

    async def _syncronize_ilias(self, ilias: IliasSycronizer):
        await ilias.syncronize()

        cookie_jar = ilias.get_cookie_jar()
        cookie_jar.save_cookies()
        authenticator = ilias.get_authenticator()

        client = cookie_jar.create_client()
        for entry in self._ilias_targets:
            tmp_dir = self._tmp_dir.new_subdir()
            organizer = Organizer(
                self.resolve(to_path(entry.target)
                             ), entry.file_conflict_resolver
            )

            downloader = IliasDownloader(
                tmp_dir,
                organizer,
                client,
                authenticator,
                entry.download_strategy,
                entry.timeout,
            )

            transformed = apply_transform(entry.transform, entry.get_results())
            if self._test_run:
                self._print_transformables(transformed)
                return organizer

            await downloader.download_all(transformed)

            if entry.clean:
                organizer.cleanup()

            self._download_summary.merge(organizer.download_summary)

        await ilias.close_client()

    def syncronize_ilias(self, ilias: IliasSycronizer):
        """
        Syncronize a given ilias instance

        Arguments:
            ilias {IliasSycronizer} -- the ILIAS Instance
        """
        asyncio.run(self._syncronize_ilias(ilias))

    def print_summary(self) -> None:
        """
        Prints the accumulated download summary.
        """
        PRETTY.summary(self._download_summary)

    @swallow_and_print_errors
    def ipd_kit(
        self,
        target: Union[PathLike, Organizer],
        url: str,
        transform: Transform = lambda x: x,
        download_strategy: IpdDownloadStrategy = ipd_download_new_or_modified,
        clean: bool = True,
        file_conflict_resolver: FileConflictResolver = resolve_prompt_user,
    ) -> Organizer:
        """
        Synchronizes a folder with a DIVA playlist.

        Arguments:
            target {Union[PathLike, Organizer]} -- The organizer / target folder to use.
            url {str} -- the url to the page

        Keyword Arguments:
            transform {Transform} -- A transformation function for the output paths. Return None
                to ignore a file. (default: {lambdax:x})
            download_strategy {DivaDownloadStrategy} -- A function to determine which files need to
                be downloaded. Can save bandwidth and reduce the number of requests.
                (default: {diva_download_new})
            clean {bool} -- Whether to clean up when the method finishes.
            file_conflict_resolver {FileConflictResolver} -- A function specifying how to deal
                with overwriting or deleting files. The default always asks the user.
        """
        tmp_dir = self._tmp_dir.new_subdir()

        if target is None:
            PRETTY.starting_synchronizer("None", "IPD", url)
            raise FatalException("Got 'None' as target directory, aborting")

        if isinstance(target, Organizer):
            organizer = target
        else:
            organizer = Organizer(self.resolve(
                to_path(target)), file_conflict_resolver)

        PRETTY.starting_synchronizer(organizer.path, "IPD", url)

        elements: List[IpdDownloadInfo] = IpdCrawler(url).crawl()
        transformed = apply_transform(transform, elements)

        if self._test_run:
            self._print_transformables(transformed)
            return organizer

        downloader = IpdDownloader(
            tmp_dir=tmp_dir, organizer=organizer, strategy=download_strategy
        )
        downloader.download_all(transformed)

        if clean:
            organizer.cleanup()

        self._download_summary.merge(organizer.download_summary)

        return organizer

    @swallow_and_print_errors
    def diva_kit(
        self,
        target: Union[PathLike, Organizer],
        playlist_location: str,
        transform: Transform = lambda x: x,
        download_strategy: DivaDownloadStrategy = diva_download_new,
        clean: bool = True,
        file_conflict_resolver: FileConflictResolver = resolve_prompt_user,
    ) -> Organizer:
        """
        Synchronizes a folder with a DIVA playlist.

        Arguments:
            organizer {Organizer} -- The organizer to use.
            playlist_location {str} -- the playlist id or the playlist URL
              in the format 'https://mediaservice.bibliothek.kit.edu/#/details/DIVA-2019-271'

        Keyword Arguments:
            transform {Transform} -- A transformation function for the output paths. Return None
                to ignore a file. (default: {lambdax:x})
            download_strategy {DivaDownloadStrategy} -- A function to determine which files need to
                be downloaded. Can save bandwidth and reduce the number of requests.
                (default: {diva_download_new})
            clean {bool} -- Whether to clean up when the method finishes.
            file_conflict_resolver {FileConflictResolver} -- A function specifying how to deal
                with overwriting or deleting files. The default always asks the user.
        """
        tmp_dir = self._tmp_dir.new_subdir()

        if playlist_location.startswith("http"):
            playlist_id = DivaPlaylistCrawler.fetch_id(
                playlist_link=playlist_location)
        else:
            playlist_id = playlist_location

        if target is None:
            PRETTY.starting_synchronizer("None", "DIVA", playlist_id)
            raise FatalException("Got 'None' as target directory, aborting")

        if isinstance(target, Organizer):
            organizer = target
        else:
            organizer = Organizer(self.resolve(
                to_path(target)), file_conflict_resolver)

        PRETTY.starting_synchronizer(organizer.path, "DIVA", playlist_id)

        crawler = DivaPlaylistCrawler(playlist_id)
        downloader = DivaDownloader(tmp_dir, organizer, download_strategy)

        info = crawler.crawl()

        transformed = apply_transform(transform, info)
        if self._test_run:
            self._print_transformables(transformed)
            return organizer

        downloader.download_all(transformed)

        if clean:
            organizer.cleanup()

        self._download_summary.merge(organizer.download_summary)

        return organizer
