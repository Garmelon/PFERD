import argparse
import asyncio
import configparser
import os
import sys
from pathlib import Path

from .auth import AuthLoadError
from .cli import PARSER, ParserLoadError, load_default_section
from .config import Config, ConfigDumpError, ConfigLoadError, ConfigOptionError
from .logging import log
from .pferd import Pferd, PferdLoadError
from .transformer import RuleParseError


def load_config_parser(args: argparse.Namespace) -> configparser.ConfigParser:
    log.explain_topic("Loading config")
    parser = configparser.ConfigParser(interpolation=None)

    if args.command is None:
        log.explain("No CLI command specified, loading config from file")
        Config.load_parser(parser, path=args.config)
    else:
        log.explain("CLI command specified, loading config from its arguments")
        if args.command:
            args.command(args, parser)

    load_default_section(args, parser)

    return parser


def load_config(args: argparse.Namespace) -> Config:
    try:
        return Config(load_config_parser(args))
    except ConfigLoadError as e:
        log.error(str(e))
        log.error_contd(e.reason)
        sys.exit(1)
    except ParserLoadError as e:
        log.error(str(e))
        sys.exit(1)


def configure_logging_from_args(args: argparse.Namespace) -> None:
    if args.explain is not None:
        log.output_explain = args.explain
    if args.status is not None:
        log.output_status = args.status
    if args.show_not_deleted is not None:
        log.output_not_deleted = args.show_not_deleted
    if args.report is not None:
        log.output_report = args.report

    # We want to prevent any unnecessary output if we're printing the config to
    # stdout, otherwise it would not be a valid config file.
    if args.dump_config_to == "-":
        log.output_explain = False
        log.output_status = False
        log.output_report = False


def configure_logging_from_config(args: argparse.Namespace, config: Config) -> None:
    # In configure_logging_from_args(), all normal logging is already disabled
    # whenever we dump the config. We don't want to override that decision with
    # values from the config file.
    if args.dump_config_to == "-":
        return

    try:
        if args.explain is None:
            log.output_explain = config.default_section.explain()
        if args.status is None:
            log.output_status = config.default_section.status()
        if args.report is None:
            log.output_report = config.default_section.report()
        if args.show_not_deleted is None:
            log.output_not_deleted = config.default_section.show_not_deleted()
    except ConfigOptionError as e:
        log.error(str(e))
        sys.exit(1)


def dump_config(args: argparse.Namespace, config: Config) -> None:
    log.explain_topic("Dumping config")

    if args.dump_config and args.dump_config_to is not None:
        log.error("--dump-config and --dump-config-to can't be specified at the same time")
        sys.exit(1)

    try:
        if args.dump_config:
            config.dump()
        elif args.dump_config_to == "-":
            config.dump_to_stdout()
        else:
            config.dump(Path(args.dump_config_to))
    except ConfigDumpError as e:
        log.error(str(e))
        log.error_contd(e.reason)
        sys.exit(1)


def main() -> None:
    args = PARSER.parse_args()

    # Configuring logging happens in two stages because CLI args have
    # precedence over config file options and loading the config already
    # produces some kinds of log messages (usually only explain()-s).
    configure_logging_from_args(args)

    config = load_config(args)

    # Now, after loading the config file, we can apply its logging settings in
    # all places that were not already covered by CLI args.
    configure_logging_from_config(args, config)

    if args.dump_config or args.dump_config_to is not None:
        dump_config(args, config)
        sys.exit()

    try:
        pferd = Pferd(config, args.crawler, args.skip)
    except PferdLoadError as e:
        log.unlock()
        log.error(str(e))
        sys.exit(1)

    try:
        if os.name == "nt":
            # A "workaround" for the windows event loop somehow crashing after
            # asyncio.run() completes. See:
            # https://bugs.python.org/issue39232
            # https://github.com/encode/httpx/issues/914#issuecomment-780023632
            # TODO Fix this properly
            loop = asyncio.get_event_loop()
            loop.run_until_complete(pferd.run(args.debug_transforms))
            loop.run_until_complete(asyncio.sleep(1))
            loop.close()
        else:
            asyncio.run(pferd.run(args.debug_transforms))
    except (ConfigOptionError, AuthLoadError) as e:
        log.unlock()
        log.error(str(e))
        sys.exit(1)
    except RuleParseError as e:
        log.unlock()
        e.pretty_print()
        sys.exit(1)
    except KeyboardInterrupt:
        log.unlock()
        log.explain_topic("Interrupted, exiting immediately")
        log.explain("Open files and connections are left for the OS to clean up")
        pferd.print_report()
        # TODO Clean up tmp files
        # And when those files *do* actually get cleaned up properly,
        # reconsider if this should really exit with 1
        sys.exit(1)
    except Exception:
        log.unlock()
        log.unexpected_exception()
        pferd.print_report()
        sys.exit(1)
    else:
        pferd.print_report()


if __name__ == "__main__":
    main()
