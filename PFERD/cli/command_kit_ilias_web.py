import argparse
import configparser
from pathlib import Path

from ..crawl.ilias.file_templates import Links
from .parser import CRAWLER_PARSER, SUBPARSERS, BooleanOptionalAction, load_crawler, show_value_error

SUBPARSER = SUBPARSERS.add_parser(
    "kit-ilias-web",
    parents=[CRAWLER_PARSER],
)

GROUP = SUBPARSER.add_argument_group(
    title="kit-ilias-web crawler arguments",
    description="arguments for the 'kit-ilias-web' crawler",
)
GROUP.add_argument(
    "target",
    type=str,
    metavar="TARGET",
    help="course id, 'desktop', or ILIAS URL to crawl"
)
GROUP.add_argument(
    "output",
    type=Path,
    metavar="OUTPUT",
    help="output directory"
)
GROUP.add_argument(
    "--username", "-u",
    type=str,
    metavar="USERNAME",
    help="user name for authentication"
)
GROUP.add_argument(
    "--keyring",
    action=BooleanOptionalAction,
    help="use the system keyring to store and retrieve passwords"
)
GROUP.add_argument(
    "--links",
    type=show_value_error(Links.from_string),
    metavar="OPTION",
    help="how to represent external links"
)
GROUP.add_argument(
    "--link-redirect-delay",
    type=int,
    metavar="SECONDS",
    help="time before 'fancy' links redirect to to their target (-1 to disable)"
)
GROUP.add_argument(
    "--videos",
    action=BooleanOptionalAction,
    help="crawl and download videos"
)
GROUP.add_argument(
    "--http-timeout", "-t",
    type=float,
    metavar="SECONDS",
    help="timeout for all HTTP requests"
)


def load(
        args: argparse.Namespace,
        parser: configparser.ConfigParser,
) -> None:
    parser["crawl:ilias"] = {}
    section = parser["crawl:ilias"]
    load_crawler(args, section)

    section["type"] = "kit-ilias-web"
    section["target"] = str(args.target)
    section["output_dir"] = str(args.output)
    section["auth"] = "auth:ilias"
    if args.links is not None:
        section["links"] = str(args.links.value)
    if args.link_redirect_delay is not None:
        section["link_redirect_delay"] = str(args.link_redirect_delay)
    if args.videos is not None:
        section["videos"] = "yes" if args.videos else "no"
    if args.http_timeout is not None:
        section["http_timeout"] = str(args.http_timeout)

    parser["auth:ilias"] = {}
    auth_section = parser["auth:ilias"]
    auth_section["type"] = "simple"
    if args.username is not None:
        auth_section["username"] = args.username
    if args.keyring:
        auth_section["type"] = "keyring"


SUBPARSER.set_defaults(command=load)
