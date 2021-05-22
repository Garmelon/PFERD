import argparse
import asyncio
import configparser
from pathlib import Path

from .cli import PARSER, load_default_section
from .config import Config, ConfigDumpError, ConfigLoadError, ConfigOptionError
from .logging import log
from .pferd import Pferd
from .version import NAME, VERSION


def load_config_parser(args: argparse.Namespace) -> configparser.ConfigParser:
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


def load_config(args: argparse.Namespace) -> Config:
    try:
        return Config(load_config_parser(args))
    except ConfigLoadError as e:
        log.error(str(e))
        log.error_contd(e.reason)
        exit(1)


def configure_logging_from_args(args: argparse.Namespace) -> None:
    if args.explain is not None:
        log.output_explain = args.explain

    # We want to prevent any unnecessary output if we're printing the config to
    # stdout, otherwise it would not be a valid config file.
    if args.dump_config == "-":
        log.output_explain = False


def configure_logging_from_config(args: argparse.Namespace, config: Config) -> None:
    # In configure_logging_from_args(), all normal logging is already disabled
    # whenever we dump the config. We don't want to override that decision with
    # values from the config file.
    if args.dump_config == "-":
        return

    try:
        if args.explain is None:
            log.output_explain = config.default_section.explain()
    except ConfigOptionError as e:
        log.error(str(e))
        exit(1)


def dump_config(args: argparse.Namespace, config: Config) -> None:
    try:
        if args.dump_config is True:
            config.dump()
        elif args.dump_config == "-":
            config.dump_to_stdout()
        else:
            config.dump(Path(args.dump_config))
    except ConfigDumpError as e:
        log.error(str(e))
        log.error_contd(e.reason)
        exit(1)


def main() -> None:
    args = PARSER.parse_args()

    if args.version:
        print(f"{NAME} {VERSION}")
        exit()

    # Configuring logging happens in two stages because CLI args have
    # precedence over config file options and loading the config already
    # produces some kinds of log messages (usually only explain()-s).
    configure_logging_from_args(args)

    config = load_config(args)

    # Now, after loading the config file, we can apply its logging settings in
    # all places that were not already covered by CLI args.
    configure_logging_from_config(args, config)

    if args.dump_config is not None:
        dump_config(args, config)
        exit()

    pferd = Pferd(config)
    try:
        asyncio.run(pferd.run())
    except KeyboardInterrupt:
        log.unlock()
        log.explain_topic("Interrupted, exiting immediately")
        log.explain("Open files and connections are left for the OS to clean up")
        log.explain("Temporary files are not cleaned up")
        # TODO Clean up tmp files
        # And when those files *do* actually get cleaned up properly,
        # reconsider what exit code to use here.
        exit(1)
    except Exception:
        log.unlock()
        log.unexpected_exception()
        exit(1)
