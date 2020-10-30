#!/usr/bin/env python

"""
A simple script to download a course by name from ILIAS.
"""

import argparse
from pathlib import Path
from urllib.parse import urlparse

from PFERD import Pferd
from PFERD.cookie_jar import CookieJar
from PFERD.ilias import (IliasCrawler, IliasElementType,
                         KitShibbolethAuthenticator)
from PFERD.utils import to_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-run", action="store_true")
    parser.add_argument('-c', '--cookies', nargs='?', default=None, help="File to store cookies in")
    parser.add_argument('--no-videos', nargs='?', default=None, help="Don't download videos")
    parser.add_argument('url', help="URL to the course page")
    parser.add_argument('folder', nargs='?', default=None, help="Folder to put stuff into")
    args = parser.parse_args()

    url = urlparse(args.url)

    cookie_jar = CookieJar(to_path(args.cookies) if args.cookies else None)
    session = cookie_jar.create_session()
    authenticator = KitShibbolethAuthenticator()
    crawler = IliasCrawler(url.scheme + '://' + url.netloc, session,
                           authenticator, lambda x, y: True)

    cookie_jar.load_cookies()

    if args.folder is not None:
        folder = args.folder
        # Initialize pferd at the *parent of the passed folder*
        # This is needed so Pferd's internal protections against escaping the working directory
        # do not trigger (e.g. if somebody names a file in ILIAS '../../bad thing.txt')
        pferd = Pferd(Path(Path(__file__).parent, folder).parent, test_run=args.test_run)
    else:
        # fetch course name from ilias
        folder = crawler.find_element_name(args.url)
        cookie_jar.save_cookies()

        # Initialize pferd at the location of the script
        pferd = Pferd(Path(__file__).parent, test_run=args.test_run)

    def dir_filter(_: Path, element: IliasElementType) -> bool:
        if args.no_videos:
            return element not in [IliasElementType.VIDEO_FILE, IliasElementType.VIDEO_FOLDER]
        return True

    pferd.enable_logging()
    # fetch
    pferd.ilias_kit_folder(
        target=folder,
        full_url=args.url,
        cookies=args.cookies,
        dir_filter=dir_filter
    )


if __name__ == "__main__":
    main()
