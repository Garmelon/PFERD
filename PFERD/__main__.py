import argparse
import asyncio
import configparser
from pathlib import Path

from .cli import PARSER, load_default_section
from .config import Config, ConfigDumpException, ConfigLoadException
from .logging import log
from .pferd import Pferd
from .version import NAME, VERSION


def load_parser(
        args: argparse.Namespace,
) -> configparser.ConfigParser:
    log.explain_topic("Loading config")
    parser = configparser.ConfigParser()

    if args.command is None:
        log.explain("No CLI command specified, loading config from file")
        Config.load_parser(parser, path=args.config)
    else:
        log.explain(f"CLI command specified, creating config for {args.command!r}")
        if args.command:
            args.command(args, parser)

    load_default_section(args, parser)
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

    # Configure log levels set by command line arguments
    if args.explain is not None:
        log.output_explain = args.explain
    if args.dump_config:
        log.output_explain = False

    if args.version:
        print(f"{NAME} {VERSION}")
        exit()

    try:
        config = Config(load_parser(args))
    except ConfigLoadException as e:
        log.error(f"Failed to load config file at path {str(e.path)!r}")
        log.error_contd(f"Reason: {e.reason}")
        exit(1)

    # Configure log levels set in the config file
    # TODO Catch config section exceptions
    if args.explain is None:
        log.output_explain = config.default_section.explain()

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
    try:
        asyncio.run(pferd.run())
    except KeyboardInterrupt:
        # TODO Clean up tmp files
        pass
