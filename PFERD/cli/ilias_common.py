import argparse
import configparser
from pathlib import Path

from .parser import BooleanOptionalAction, ParserLoadError, show_value_error
from ..crawl.ilias.file_templates import Links


def configure_common_group_args(group: argparse._ArgumentGroup) -> None:
    group.add_argument(
        "target",
        type=str,
        metavar="TARGET",
        help="course id, 'desktop', or ILIAS URL to crawl"
    )
    group.add_argument(
        "output",
        type=Path,
        metavar="OUTPUT",
        help="output directory"
    )
    group.add_argument(
        "--username", "-u",
        type=str,
        metavar="USERNAME",
        help="user name for authentication"
    )
    group.add_argument(
        "--keyring",
        action=BooleanOptionalAction,
        help="use the system keyring to store and retrieve passwords"
    )
    group.add_argument(
        "--credential-file",
        type=Path,
        metavar="PATH",
        help="read username and password from a credential file"
    )
    group.add_argument(
        "--links",
        type=show_value_error(Links.from_string),
        metavar="OPTION",
        help="how to represent external links"
    )
    group.add_argument(
        "--link-redirect-delay",
        type=int,
        metavar="SECONDS",
        help="time before 'fancy' links redirect to to their target (-1 to disable)"
    )
    group.add_argument(
        "--videos",
        action=BooleanOptionalAction,
        help="crawl and download videos"
    )
    group.add_argument(
        "--forums",
        action=BooleanOptionalAction,
        help="crawl and download forum posts"
    )
    group.add_argument(
        "--http-timeout", "-t",
        type=float,
        metavar="SECONDS",
        help="timeout for all HTTP requests"
    )


def ilias_common_load(
    section: configparser.SectionProxy,
    args: argparse.Namespace,
    parser: configparser.ConfigParser,
) -> None:
    section["target"] = str(args.target)
    section["output_dir"] = str(args.output)
    section["auth"] = "auth:ilias"
    if args.links is not None:
        section["links"] = str(args.links.value)
    if args.link_redirect_delay is not None:
        section["link_redirect_delay"] = str(args.link_redirect_delay)
    if args.videos is not None:
        section["videos"] = "yes" if args.videos else "no"
    if args.forums is not None:
        section["forums"] = "yes" if args.forums else "no"
    if args.http_timeout is not None:
        section["http_timeout"] = str(args.http_timeout)

    parser["auth:ilias"] = {}
    auth_section = parser["auth:ilias"]
    if args.credential_file is not None:
        if args.username is not None:
            raise ParserLoadError("--credential-file and --username can't be used together")
        if args.keyring:
            raise ParserLoadError("--credential-file and --keyring can't be used together")
        auth_section["type"] = "credential-file"
        auth_section["path"] = str(args.credential_file)
    elif args.keyring:
        auth_section["type"] = "keyring"
    else:
        auth_section["type"] = "simple"
    if args.username is not None:
        auth_section["username"] = args.username
