import argparse
import configparser

from ..logging import log
from .common_ilias_args import configure_common_group_args, load_common
from .parser import CRAWLER_PARSER, SUBPARSERS, load_crawler

COMMAND_NAME = "kit-ilias-web"

SUBPARSER = SUBPARSERS.add_parser(
    COMMAND_NAME,
    parents=[CRAWLER_PARSER],
)

GROUP = SUBPARSER.add_argument_group(
    title=f"{COMMAND_NAME} crawler arguments",
    description=f"arguments for the '{COMMAND_NAME}' crawler",
)

configure_common_group_args(GROUP)


def load(
        args: argparse.Namespace,
        parser: configparser.ConfigParser,
) -> None:
    log.explain(f"Creating config for command '{COMMAND_NAME}'")

    parser["crawl:ilias"] = {}
    section = parser["crawl:ilias"]
    load_crawler(args, section)

    section["type"] = COMMAND_NAME
    load_common(section, args, parser)


SUBPARSER.set_defaults(command=load)
