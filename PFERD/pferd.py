"""
Convenience functions for using PFERD.
"""

import logging
from pathlib import Path
from typing import Optional

from .cookie_jar import CookieJar
from .ilias import (IliasAuthenticator, IliasCrawler, IliasDirectoryFilter,
                    IliasDownloader, KitShibbolethAuthenticator)
from .ilias.download_strategies import (DownloadStrategy,
                                        download_modified_or_new)
from .location import Location
from .organizer import Organizer
from .tmp_dir import TmpDir
from .transform import Transform, apply_transform
from .utils import PrettyLogger

# TODO save known-good cookies as soon as possible


LOGGER = logging.getLogger(__name__)
PRETTY = PrettyLogger(LOGGER)


class Pferd(Location):
    # pylint: disable=too-many-arguments
    """
    The main entrypoint in your Pferd usage: This class combines a number of
    useful shortcuts for running synchronizers in a single interface.
    """

    def __init__(self, base_dir: Path, tmp_dir: Path = Path(".tmp")):
        super().__init__(Path(base_dir))

        self._tmp_dir = TmpDir(self.resolve(tmp_dir))

    def _ilias(
            self,
            target: Path,
            base_url: str,
            course_id: str,
            authenticator: IliasAuthenticator,
            cookies: Optional[Path],
            dir_filter: IliasDirectoryFilter,
            transform: Transform,
            download_strategy: DownloadStrategy,
    ) -> None:
        # pylint: disable=too-many-locals
        cookie_jar = CookieJar(cookies)
        session = cookie_jar.create_session()
        tmp_dir = self._tmp_dir.new_subdir()
        organizer = Organizer(self.resolve(target))

        crawler = IliasCrawler(base_url, course_id, session, authenticator, dir_filter)
        downloader = IliasDownloader(tmp_dir, organizer, session, authenticator)

        cookie_jar.load_cookies()
        info = crawler.crawl()
        cookie_jar.save_cookies()
        downloader.download_all(
            [
                info for info in apply_transform(transform, info)
                if download_strategy(organizer, info)
            ]
        )
        cookie_jar.save_cookies()

    def ilias_kit(
            self,
            target: Path,
            course_id: str,
            dir_filter: IliasDirectoryFilter = lambda x: True,
            transform: Transform = lambda x: x,
            cookies: Optional[Path] = None,
            username: Optional[str] = None,
            password: Optional[str] = None,
            download_strategy: DownloadStrategy = download_modified_or_new,
    ) -> None:
        """
        Synchronizes a folder with the ILIAS instance of the KIT.

        Arguments:
            target {Path} -- the target path to write the data to
            course_id {str} -- the id of the main course page (found in the URL after ref_id
                when opening the course homepage)

        Keyword Arguments:
            dir_filter {IliasDirectoryFilter} -- A filter for directories. Will be applied on the
                crawler level, these directories and all of their content is skipped.
                (default: {lambdax:True})
            transform {Transform} -- A transformation function for the output paths. Return None
                to ignore a file. (default: {lambdax:x})
            cookies {Optional[Path]} -- The path to store and load cookies from.
                (default: {None})
            username {Optional[str]} -- The SCC username. If none is given, it will prompt
                the user. (default: {None})
            password {Optional[str]} -- The SCC password. If none is given, it will prompt
                the user. (default: {None})
            download_strategy {DownloadStrategy} -- A function to determine which files need to
                be downloaded. Can save bandwidth and reduce the number of requests.
                (default: {download_modified_or_new})
        """
        # This authenticator only works with the KIT ilias instance.
        authenticator = KitShibbolethAuthenticator(username=username, password=password)
        PRETTY.starting_synchronizer(target, "ILIAS", course_id)
        self._ilias(
            target=target,
            base_url="https://ilias.studium.kit.edu/",
            course_id=course_id,
            authenticator=authenticator,
            cookies=cookies,
            dir_filter=dir_filter,
            transform=transform,
            download_strategy=download_strategy,
        )
