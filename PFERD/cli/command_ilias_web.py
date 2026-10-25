import argparse
import configparser

from ..logging import log
from .common_ilias_args import configure_common_group_args, load_common
from .parser import CRAWLER_PARSER, SUBPARSERS, ParserLoadError, load_crawler

COMMAND_NAME = "ilias-web"

SUBPARSER = SUBPARSERS.add_parser(
    COMMAND_NAME,
    parents=[CRAWLER_PARSER],
)

GROUP = SUBPARSER.add_argument_group(
    title=f"{COMMAND_NAME} crawler arguments",
    description=f"arguments for the '{COMMAND_NAME}' crawler",
)

GROUP.add_argument(
    "--base-url",
    type=str,
    metavar="BASE_URL",
    help="The base url of the ilias instance",
)

GROUP.add_argument(
    "--login-type",
    type=str,
    choices=["local", "shibboleth"],
    help="How to log in (default: local if --client-id is given, otherwise shibboleth)",
)

GROUP.add_argument(
    "--client-id",
    type=str,
    metavar="CLIENT_ID",
    help="The client id of the ilias instance",
)

configure_common_group_args(GROUP)


def load(args: argparse.Namespace, parser: configparser.ConfigParser) -> None:
    log.explain(f"Creating config for command '{COMMAND_NAME}'")

    parser["crawl:ilias"] = {}
    section = parser["crawl:ilias"]
    load_crawler(args, section)

    section["type"] = COMMAND_NAME
    if args.base_url is not None:
        section["base_url"] = args.base_url
    login_type = args.login_type
    if login_type is None:
        login_type = "local" if args.client_id is not None else "shibboleth"
    if login_type == "local" and args.client_id is None:
        raise ParserLoadError("--login-type local requires --client-id")
    section["login_type"] = login_type
    if args.client_id is not None:
        section["client_id"] = args.client_id

    load_common(section, args, parser)


SUBPARSER.set_defaults(command=load)
