from pathlib import Path
from typing import Optional

from .cookie_jar import CookieJar
from .ilias import (IliasAuthenticator, IliasCrawler, IliasDownloader,
                    IliasFilter, KitShibbolethAuthenticator)
from .organizer import Organizer
from .tmp_dir import TmpDir
from .transform import Transform, apply_transform
from .utils import Location


class Pferd(Location):
    # pylint: disable=too-many-arguments

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
            filter_: IliasFilter,
            transform: Transform,
    ) -> None:
        cookie_jar = CookieJar(cookies)
        session = cookie_jar.create_session()
        tmp_dir = self._tmp_dir.new_subdir()
        organizer = Organizer(self.resolve(target))

        crawler = IliasCrawler(base_url, course_id, session, authenticator, filter_)
        downloader = IliasDownloader(tmp_dir, organizer, session, authenticator)

        cookie_jar.load_cookies()
        info = crawler.crawl()
        cookie_jar.save_cookies()
        downloader.download_all(apply_transform(transform, info))
        cookie_jar.save_cookies()

    def ilias_kit(
            self,
            target: Path,
            course_id: str,
            filter_: IliasFilter = lambda x: True,
            transform: Transform = lambda x: x,
            cookies: Optional[Path] = None,
            username: Optional[str] = None,
            password: Optional[str] = None,
    ) -> None:
        # This authenticator only works with the KIT ilias instance.
        authenticator = KitShibbolethAuthenticator(username=username, password=password)
        self._ilias(
            target=target,
            base_url="https://ilias.studium.kit.edu/",
            course_id=course_id,
            authenticator=authenticator,
            cookies=cookies,
            filter_=filter_,
            transform=transform,
        )
