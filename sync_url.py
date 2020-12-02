#!/usr/bin/env python

"""
A simple script to download a course by name from ILIAS.
"""

import argparse
from pathlib import Path, PurePath
from urllib.parse import urlparse

from PFERD import Pferd
from PFERD.cookie_jar import CookieJar
from PFERD.ilias import (IliasCrawler, IliasElementType,
                         KitShibbolethAuthenticator)
from PFERD.organizer import FileConflictResolution, resolve_prompt_user
from PFERD.transform import sanitize_windows_path
from PFERD.utils import to_path


def _resolve_overwrite(_path: PurePath) -> FileConflictResolution:
    return FileConflictResolution.OVERWRITE_EXISTING


def _resolve_default(_path: PurePath) -> FileConflictResolution:
    return FileConflictResolution.DEFAULT


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-run", action="store_true")
    parser.add_argument('-c', '--cookies', nargs='?', default=None, help="File to store cookies in")
    parser.add_argument('--no-videos', nargs='?', default=None, help="Don't download videos")
    parser.add_argument('-d', '--default', action="store_true",
                        help="Don't prompt for confirmations and use sane defaults")
    parser.add_argument('-r', '--remove', action="store_true",
                        help="Remove and overwrite files without prompting for confirmation")
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

    folder = Path(args.folder)
    if args.folder is None:
        element_name = crawler.find_element_name(args.url)
        if not element_name:
            print("Error, could not get element name. Please specify a folder yourself.")
            return
        folder = Path(element_name)
        cookie_jar.save_cookies()

    # files may not escape the pferd_root with relative paths
    # note: Path(Path.cwd, Path(folder)) == Path(folder) if it is an absolute path
    pferd_root = Path(Path.cwd(), Path(folder)).parent
    target = folder.name
    pferd = Pferd(pferd_root, test_run=args.test_run)

    def dir_filter(_: Path, element: IliasElementType) -> bool:
        if args.no_videos:
            return element not in [IliasElementType.VIDEO_FILE, IliasElementType.VIDEO_FOLDER]
        return True

    if args.default:
        file_confilict_resolver = _resolve_default
    elif args.remove:
        file_confilict_resolver = _resolve_overwrite
    else:
        file_confilict_resolver = resolve_prompt_user

    pferd.enable_logging()
    # fetch
    pferd.ilias_kit_folder(
        target=target,
        full_url=args.url,
        cookies=args.cookies,
        dir_filter=dir_filter,
        transform=sanitize_windows_path,
        file_conflict_resolver=file_confilict_resolver
    )


if __name__ == "__main__":
    main()
