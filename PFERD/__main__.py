import argparse
import asyncio
from pathlib import Path

from .config import Config, ConfigDumpException, ConfigLoadException
from .pferd import Pferd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", "-c",
        type=Path,
        metavar="PATH",
        help="specify custom config file path",
    )
    parser.add_argument(
        "--dump-config",
        nargs="?",
        const=True,
        type=Path,
        metavar="PATH",
        help="dump current configuration to a file and exit."
        " Uses default config file path if no path is specified",
    )
    args = parser.parse_args()

    try:
        config_parser = Config.load_parser(args.config)
        config = Config(config_parser)
    except ConfigLoadException:
        exit(1)

    if args.dump_config:
        path = None if args.dump_config is True else args.dump_config
        try:
            config.dump(path)
        except ConfigDumpException:
            exit(1)
        exit()

    pferd = Pferd(config)
    asyncio.run(pferd.run())
