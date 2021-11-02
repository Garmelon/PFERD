import argparse
import configparser
from pathlib import Path

from ..logging import log
from .parser import CRAWLER_PARSER, SUBPARSERS, load_crawler

SUBPARSER = SUBPARSERS.add_parser(
    "kit-ipd",
    parents=[CRAWLER_PARSER],
)

GROUP = SUBPARSER.add_argument_group(
    title="kit ipd crawler arguments",
    description="arguments for the 'kit-ipd' crawler",
)
GROUP.add_argument(
    "--link-regex",
    type=str,
    metavar="REGEX",
    help="href-matching regex to identify downloadable files"
)
GROUP.add_argument(
    "target",
    type=str,
    metavar="TARGET",
    help="url to crawl"
)
GROUP.add_argument(
    "output",
    type=Path,
    metavar="OUTPUT",
    help="output directory"
)


def load(
        args: argparse.Namespace,
        parser: configparser.ConfigParser,
) -> None:
    log.explain("Creating config for command 'kit-ipd'")

    parser["crawl:kit-ipd"] = {}
    section = parser["crawl:kit-ipd"]
    load_crawler(args, section)

    section["type"] = "kit-ipd"
    section["target"] = str(args.target)
    section["output_dir"] = str(args.output)
    if args.link_regex:
        section["link_regex"] = str(args.link_regex)


SUBPARSER.set_defaults(command=load)
