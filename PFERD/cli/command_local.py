import argparse
import configparser
from pathlib import Path

from ..logging import log
from .parser import CRAWLER_PARSER, SUBPARSERS, load_crawler

SUBPARSER = SUBPARSERS.add_parser(
    "local",
    parents=[CRAWLER_PARSER],
)

GROUP = SUBPARSER.add_argument_group(
    title="local crawler arguments",
    description="arguments for the 'local' crawler",
)
GROUP.add_argument(
    "target",
    type=Path,
    metavar="TARGET",
    help="directory to crawl"
)
GROUP.add_argument(
    "output",
    type=Path,
    metavar="OUTPUT",
    help="output directory"
)
GROUP.add_argument(
    "--crawl-delay",
    type=float,
    metavar="SECONDS",
    help="artificial delay to simulate for crawl requests"
)
GROUP.add_argument(
    "--download-delay",
    type=float,
    metavar="SECONDS",
    help="artificial delay to simulate for download requests"
)
GROUP.add_argument(
    "--download-speed",
    type=int,
    metavar="BYTES_PER_SECOND",
    help="download speed to simulate"
)


def load(
        args: argparse.Namespace,
        parser: configparser.ConfigParser,
) -> None:
    log.explain("Creating config for command 'local'")

    parser["crawl:local"] = {}
    section = parser["crawl:local"]
    load_crawler(args, section)

    section["type"] = "local"
    section["target"] = str(args.target)
    section["output_dir"] = str(args.output)
    if args.crawl_delay is not None:
        section["crawl_delay"] = str(args.crawl_delay)
    if args.download_delay is not None:
        section["download_delay"] = str(args.download_delay)
    if args.download_speed is not None:
        section["download_speed"] = str(args.download_speed)


SUBPARSER.set_defaults(command=load)
