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
from PFERD.organizer import (ConflictType, FileConflictResolution,
                             FileConflictResolver, resolve_prompt_user)
from PFERD.transform import sanitize_windows_path
from PFERD.utils import to_path


def _resolve_remote_first(_path: PurePath, _conflict: ConflictType) -> FileConflictResolution:
    return FileConflictResolution.DESTROY_EXISTING


def _resolve_local_first(_path: PurePath, _conflict: ConflictType) -> FileConflictResolution:
    return FileConflictResolution.KEEP_EXISTING


def _resolve_no_delete(_path: PurePath, conflict: ConflictType) -> FileConflictResolution:
    # Update files
    if conflict == ConflictType.FILE_OVERWRITTEN:
        return FileConflictResolution.DESTROY_EXISTING
    if conflict == ConflictType.MARKED_FILE_OVERWRITTEN:
        return FileConflictResolution.DESTROY_EXISTING
    # But do not delete them
    return FileConflictResolution.KEEP_EXISTING


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-run", action="store_true")
    parser.add_argument('-c', '--cookies', nargs='?', default=None, help="File to store cookies in")
    parser.add_argument('--no-videos', nargs='?', default=None, help="Don't download videos")
    parser.add_argument('--local-first', action="store_true",
                        help="Don't prompt for confirmation, keep existing files")
    parser.add_argument('--remote-first', action="store_true",
                        help="Don't prompt for confirmation, delete and overwrite local files")
    parser.add_argument('--no-delete', action="store_true",
                        help="Don't prompt for confirmation, overwrite local files, don't delete")
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

    if args.folder is None:
        element_name = crawler.find_element_name(args.url)
        if not element_name:
            print("Error, could not get element name. Please specify a folder yourself.")
            return
        folder = Path(element_name)
        cookie_jar.save_cookies()
    else:
        folder = Path(args.folder)

    # files may not escape the pferd_root with relative paths
    # note: Path(Path.cwd, Path(folder)) == Path(folder) if it is an absolute path
    pferd_root = Path(Path.cwd(), Path(folder)).parent
    target = folder.name
    pferd = Pferd(pferd_root, test_run=args.test_run)

    def dir_filter(_: Path, element: IliasElementType) -> bool:
        if args.no_videos:
            return element not in [IliasElementType.VIDEO_FILE, IliasElementType.VIDEO_FOLDER]
        return True

    if args.remote_first:
        file_confilict_resolver: FileConflictResolver = _resolve_remote_first
    elif args.local_first:
        file_confilict_resolver = _resolve_local_first
    elif args.no_delete:
        file_confilict_resolver = _resolve_no_delete
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
