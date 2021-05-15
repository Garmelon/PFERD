import argparse
import asyncio
import configparser
from pathlib import Path

from .config import Config, ConfigDumpException, ConfigLoadException
from .output_dir import OnConflict, Redownload
from .pferd import Pferd

GENERAL_PARSER = argparse.ArgumentParser(add_help=False)
GENERAL_PARSER.add_argument(
    "--config", "-c",
    type=Path,
    metavar="PATH",
    help="custom config file"
)
GENERAL_PARSER.add_argument(
    "--dump-config",
    nargs="?",
    const=True,
    metavar="PATH",
    help="dump current configuration to a file and exit."
    " Uses default config file path if no path is specified"
)
GENERAL_PARSER.add_argument(
    "--crawler",
    action="append",
    type=str,
    metavar="NAME",
    help="only execute a single crawler."
    " Can be specified multiple times to execute multiple crawlers"
)
GENERAL_PARSER.add_argument(
    "--working-dir",
    type=Path,
    metavar="PATH",
    help="custom working directory"
)


def load_general(
        args: argparse.Namespace,
        parser: configparser.ConfigParser,
) -> None:
    section = parser[parser.default_section]

    if args.working_dir is not None:
        section["working_dir"] = str(args.working_dir)


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


PARSER = argparse.ArgumentParser(parents=[GENERAL_PARSER])
PARSER.set_defaults(command=None)
SUBPARSERS = PARSER.add_subparsers(title="crawlers")


LOCAL_CRAWLER = SUBPARSERS.add_parser(
    "local",
    parents=[GENERAL_PARSER, CRAWLER_PARSER],
)
LOCAL_CRAWLER.set_defaults(command="local")
LOCAL_CRAWLER_GROUP = LOCAL_CRAWLER.add_argument_group(
    title="local crawler arguments",
    description="arguments for the 'local' crawler",
)
LOCAL_CRAWLER_GROUP.add_argument(
    "target",
    type=Path,
    metavar="TARGET",
    help="directory to crawl"
)
LOCAL_CRAWLER_GROUP.add_argument(
    "output",
    type=Path,
    metavar="OUTPUT",
    help="output directory"
)
LOCAL_CRAWLER_GROUP.add_argument(
    "--crawl-delay",
    type=float,
    metavar="SECONDS",
    help="artificial delay to simulate for crawl requests"
)
LOCAL_CRAWLER_GROUP.add_argument(
    "--download-delay",
    type=float,
    metavar="SECONDS",
    help="artificial delay to simulate for download requests"
)
LOCAL_CRAWLER_GROUP.add_argument(
    "--download-speed",
    type=int,
    metavar="BYTES_PER_SECOND",
    help="download speed to simulate"
)


def load_local_crawler(
        args: argparse.Namespace,
        parser: configparser.ConfigParser,
) -> None:
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


def load_parser(
        args: argparse.Namespace,
) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()

    if args.command is None:
        Config.load_parser(parser, path=args.config)
    elif args.command == "local":
        load_local_crawler(args, parser)

    load_general(args, parser)
    prune_crawlers(args, parser)

    return parser


def prune_crawlers(
        args: argparse.Namespace,
        parser: configparser.ConfigParser,
) -> None:
    if not args.crawler:
        return

    for section in parser.sections():
        if section.startswith("crawl:"):
            # TODO Use removeprefix() when switching to 3.9
            name = section[len("crawl:"):]
            if name not in args.crawler:
                parser.remove_section(section)

    # TODO Check if crawlers actually exist


def main() -> None:
    args = PARSER.parse_args()

    try:
        config = Config(load_parser(args))
    except ConfigLoadException:
        exit(1)

    if args.dump_config is not None:
        try:
            if args.dump_config is True:
                config.dump()
            elif args.dump_config == "-":
                config.dump_to_stdout()
            else:
                config.dump(Path(args.dump_config))
        except ConfigDumpException:
            exit(1)
        exit()

    pferd = Pferd(config)
    asyncio.run(pferd.run())
