import argparse
import configparser
from pathlib import Path

from ..output_dir import OnConflict, Redownload
from ..version import NAME, VERSION

CRAWLER_PARSER = argparse.ArgumentParser(add_help=False)
CRAWLER_PARSER_GROUP = CRAWLER_PARSER.add_argument_group(
    title="general crawler arguments",
    description="arguments common to all crawlers",
)
CRAWLER_PARSER_GROUP.add_argument(
    "--redownload",
    type=Redownload.from_string,
    metavar="OPTION",
    help="when to redownload a file that's already present locally"
)
CRAWLER_PARSER_GROUP.add_argument(
    "--on-conflict",
    type=OnConflict.from_string,
    metavar="OPTION",
    help="what to do when local and remote files or directories differ"
)
CRAWLER_PARSER_GROUP.add_argument(
    "--transform", "-t",
    action="append",
    type=str,
    metavar="RULE",
    help="add a single transformation rule. Can be specified multiple times"
)
CRAWLER_PARSER_GROUP.add_argument(
    "--max-concurrent-tasks",
    type=int,
    metavar="N",
    help="maximum number of concurrent tasks (crawling, downloading)"
)
CRAWLER_PARSER_GROUP.add_argument(
    "--max-concurrent-downloads",
    type=int,
    metavar="N",
    help="maximum number of tasks that may download data at the same time"
)
CRAWLER_PARSER_GROUP.add_argument(
    "--delay-between-tasks",
    type=float,
    metavar="SECONDS",
    help="time the crawler should wait between subsequent tasks"
)


def load_crawler(
        args: argparse.Namespace,
        section: configparser.SectionProxy,
) -> None:
    if args.redownload is not None:
        section["redownload"] = args.redownload.value
    if args.on_conflict is not None:
        section["on_conflict"] = args.on_conflict.value
    if args.transform is not None:
        section["transform"] = "\n" + "\n".join(args.transform)
    if args.max_concurrent_tasks is not None:
        section["max_concurrent_tasks"] = str(args.max_concurrent_tasks)
    if args.max_concurrent_downloads is not None:
        section["max_concurrent_downloads"] = str(args.max_concurrent_downloads)
    if args.delay_between_tasks is not None:
        section["delay_between_tasks"] = str(args.delay_between_tasks)


PARSER = argparse.ArgumentParser()
PARSER.set_defaults(command=None)
PARSER.add_argument(
    "--version",
    action="version",
    version=f"{NAME} {VERSION}",
)
PARSER.add_argument(
    "--config", "-c",
    type=Path,
    metavar="PATH",
    help="custom config file"
)
PARSER.add_argument(
    "--dump-config",
    nargs="?",
    const=True,
    metavar="PATH",
    help="dump current configuration to a file and exit."
    " Uses default config file path if no path is specified"
)
PARSER.add_argument(
    "--crawler", "-C",
    action="append",
    type=str,
    metavar="NAME",
    help="only execute a single crawler."
    " Can be specified multiple times to execute multiple crawlers"
)
PARSER.add_argument(
    "--working-dir",
    type=Path,
    metavar="PATH",
    help="custom working directory"
)
PARSER.add_argument(
    "--explain", "-e",
    # TODO Use argparse.BooleanOptionalAction after updating to 3.9
    action="store_const",
    const=True,
    help="log and explain in detail what PFERD is doing"
)


def load_default_section(
        args: argparse.Namespace,
        parser: configparser.ConfigParser,
) -> None:
    section = parser[parser.default_section]

    if args.working_dir is not None:
        section["working_dir"] = str(args.working_dir)
    if args.explain is not None:
        section["explain"] = "true" if args.explain else "false"


SUBPARSERS = PARSER.add_subparsers(title="crawlers")
