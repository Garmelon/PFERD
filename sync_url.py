#!/usr/bin/env python

"""
A simple script to download a course by name from ILIAS.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from PFERD import Pferd
from PFERD.cookie_jar import CookieJar
from PFERD.ilias import (IliasCrawler, IliasElementType,
                         KitShibbolethAuthenticator,
                         KeyringKitShibbolethAuthenticator)
from PFERD.logging import PrettyLogger, enable_logging
from PFERD.utils import to_path

_LOGGER = logging.getLogger("sync_url")
_PRETTY = PrettyLogger(_LOGGER)


def _extract_credentials(file_path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not file_path:
        return (None, None)

    if not Path(file_path).exists():
        _PRETTY.error("Credential file does not exist")
        sys.exit(1)

    with open(file_path, "r") as file:
        first_line = file.readline()
        read_name, *read_password = first_line.split(":", 1)

        name = read_name if read_name else None
        password = read_password[0] if read_password else None
        return (name, password)


def main() -> None:
    enable_logging(name="sync_url")

    parser = argparse.ArgumentParser()
    parser.add_argument("--test-run", action="store_true")
    parser.add_argument('-c', '--cookies', nargs='?', default=None, help="File to store cookies in")
    parser.add_argument('--credential-file', nargs='?', default=None,
                        help="Path to a file containing credentials for Ilias. The file must have "
                        "one line in the following format: '<user>:<password>'")
    parser.add_argument('--no-videos', nargs='?', default=None, help="Don't download videos")
    parser.add_argument("-k", "--keyring", action="store_true", help="Use the system keyring service for authentication")
    parser.add_argument('url', help="URL to the course page")
    parser.add_argument('folder', nargs='?', default=None, help="Folder to put stuff into")
    args = parser.parse_args()

    cookie_jar = CookieJar(to_path(args.cookies) if args.cookies else None)
    session = cookie_jar.create_session()

    username, password = _extract_credentials(args.credential_file)
    if args.keyring:
        authenticator = KeyringKitShibbolethAuthenticator(
            username=username, password=password)
    else:
        authenticator = KitShibbolethAuthenticator(
            username=username, password=password)

    url = urlparse(args.url)
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
    (username, password) = authenticator._auth.get_credentials()
    pferd.ilias_kit_folder(
        target=folder,
        full_url=args.url,
        cookies=args.cookies,
        dir_filter=dir_filter,
        username=username,
        password=password
    )


if __name__ == "__main__":
    main()
