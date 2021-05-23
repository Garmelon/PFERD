import argparse
import configparser
from pathlib import Path

from .parser import CRAWLER_PARSER, SUBPARSERS, load_crawler

SUBPARSER = SUBPARSERS.add_parser(
    "kit-ilias-web",
    parents=[CRAWLER_PARSER],
)

GROUP = SUBPARSER.add_argument_group(
    title="KIT ILIAS web-crawler arguments",
    description="arguments for the 'kit-ilias-web' crawler",
)
GROUP.add_argument(
    "target",
    type=str,
    metavar="TARGET",
    help="course id, 'desktop', or ILIAS https-URL to crawl"
)
GROUP.add_argument(
    "output",
    type=Path,
    metavar="OUTPUT",
    help="output directory"
)
GROUP.add_argument(
    "--videos",
    # TODO Use argparse.BooleanOptionalAction after updating to 3.9
    action="store_const",
    const=True,
    help="crawl and download videos"
)
GROUP.add_argument(
    "--username",
    type=str,
    metavar="USER_NAME",
    help="user name for authentication"
)
GROUP.add_argument(
    "--link-file-redirect-delay",
    type=int,
    metavar="SECONDS",
    help="delay before external link files redirect you to their target (-1 to disable)"
)
GROUP.add_argument(
    "--link-file-plaintext",
    # TODO Use argparse.BooleanOptionalAction after updating to 3.9
    action="store_const",
    const=True,
    help="use plain text files for external links"
)


def load(
        args: argparse.Namespace,
        parser: configparser.ConfigParser,
) -> None:
    parser["crawl:kit-ilias-web"] = {}
    section = parser["crawl:kit-ilias-web"]
    load_crawler(args, section)

    section["type"] = "kit-ilias-web"
    section["target"] = str(args.target)
    section["output_dir"] = str(args.output)
    section["auth"] = "auth:kit-ilias-web"
    if args.link_file_redirect_delay is not None:
        section["link_file_redirect_delay"] = str(args.link_file_redirect_delay)
    if args.link_file_plaintext is not None:
        section["link_file_plaintext"] = str(args.link_file_plaintext)
    if args.videos is not None:
        section["videos"] = str(False)

    parser["auth:kit-ilias-web"] = {}
    auth_section = parser["auth:kit-ilias-web"]
    auth_section["type"] = "simple"

    if args.username is not None:
        auth_section["username"] = str(args.username)


SUBPARSER.set_defaults(command=load)
