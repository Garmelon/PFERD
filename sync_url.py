#!/usr/bin/env python

import argparse
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from PFERD import Pferd
from PFERD.cookie_jar import CookieJar
from PFERD.utils import to_path
from PFERD.ilias.authenticators import KitShibbolethAuthenticator
from PFERD.ilias.crawler import IliasCrawler

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-run", action="store_true")
    parser.add_argument('-c', '--cookies', nargs='?', default=None, help="File to store cookies in")
    parser.add_argument('url', help="URL to the course page")
    parser.add_argument('folder', nargs='?', default=None, help="Folder to put stuff into")
    args = parser.parse_args()

    pferd = Pferd(Path(__file__).parent, test_run=args.test_run)
    pferd.enable_logging()

    # parse provided course URL
    url = urlparse(args.url)
    query = parse_qs(url.query)
    id = int(query['ref_id'][0])

    if args.folder is None:
        # fetch course name from ilias
        cookie_jar = CookieJar(to_path(args.cookies) if args.cookies else None)
        session = cookie_jar.create_session()
        authenticator = KitShibbolethAuthenticator()
        crawler = IliasCrawler(url.scheme + '://' + url.netloc, session, authenticator, lambda x, y: True)

        cookie_jar.load_cookies()
        folder = crawler.find_course_name(id)
        cookie_jar.save_cookies()
    else:
        folder = args.folder

    # fetch
    pferd.ilias_kit(target=folder, course_id=str(id), cookies=args.cookies)

if __name__ == "__main__":
    main()
