import argparse
import configparser
from pathlib import Path

from ..logging import log
from .parser import CRAWLER_PARSER, SUBPARSERS, load_crawler

SUBPARSER = SUBPARSERS.add_parser(
    "lfcps",
    parents=[CRAWLER_PARSER],
)

GROUP = SUBPARSER.add_argument_group(
    title="lfcps crawler arguments",
    description="arguments for the 'lfcps' crawler",
)
GROUP.add_argument(
    "--link-regex",
    type=str,
    metavar="REGEX",
    help="href-matching regex to identify downloadable files",
)
GROUP.add_argument(
    "--basic-auth",
    action="store_true",
    help="enable basic authentication",
)
GROUP.add_argument(
    "target",
    type=str,
    nargs="?",
    metavar="TARGET",
    help="url of the schedule page to crawl (default: https://lfcps.org/course/lfcps-schedule.html)",
)
GROUP.add_argument(
    "output",
    type=Path,
    metavar="OUTPUT",
    help="output directory",
)


def load(
    args: argparse.Namespace,
    parser: configparser.ConfigParser,
) -> None:
    log.explain("Creating config for command 'lfcps'")

    parser["crawl:lfcps"] = {}
    section = parser["crawl:lfcps"]
    load_crawler(args, section)

    section["type"] = "lfcps"
    section["output_dir"] = str(args.output)
    if args.target:
        section["target"] = str(args.target)
    if args.link_regex:
        section["link_regex"] = str(args.link_regex)

    if args.basic_auth:
        section["auth"] = "auth:lfcps"
        parser["auth:lfcps"] = {}
        auth_section = parser["auth:lfcps"]
        auth_section["type"] = "simple"


SUBPARSER.set_defaults(command=load)
