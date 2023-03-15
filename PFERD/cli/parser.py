import argparse
import configparser
from argparse import ArgumentTypeError
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence, Union

from ..output_dir import OnConflict, Redownload
from ..version import NAME, VERSION


class ParserLoadError(Exception):
    pass


# TODO Replace with argparse version when updating to 3.9?
class BooleanOptionalAction(argparse.Action):
    def __init__(
            self,
            option_strings: List[str],
            dest: Any,
            default: Any = None,
            type: Any = None,
            choices: Any = None,
            required: Any = False,
            help: Any = None,
            metavar: Any = None,
    ):
        if len(option_strings) != 1:
            raise ValueError("There must be exactly one option string")
        [self.name] = option_strings
        if not self.name.startswith("--"):
            raise ValueError(f"{self.name!r} doesn't start with '--'")
        if self.name.startswith("--no-"):
            raise ValueError(f"{self.name!r} starts with '--no-'")

        options = [self.name, "--no-" + self.name[2:]]

        super().__init__(
            options,
            dest,
            nargs=0,
            default=default,
            type=type,
            choices=choices,
            required=required,
            help=help,
            metavar=metavar,
        )

    def __call__(
            self,
            parser: argparse.ArgumentParser,
            namespace: argparse.Namespace,
            values: Union[str, Sequence[Any], None],
            option_string: Optional[str] = None,
    ) -> None:
        if option_string and option_string in self.option_strings:
            value = not option_string.startswith("--no-")
            setattr(namespace, self.dest, value)

    def format_usage(self) -> str:
        return "--[no-]" + self.name[2:]


def show_value_error(inner: Callable[[str], Any]) -> Callable[[str], Any]:
    """
    Some validation functions (like the from_string in our enums) raise a ValueError.
    Argparse only pretty-prints ArgumentTypeErrors though, so we need to wrap our ValueErrors.
    """
    def wrapper(input: str) -> Any:
        try:
            return inner(input)
        except ValueError as e:
            raise ArgumentTypeError(e)
    return wrapper


CRAWLER_PARSER = argparse.ArgumentParser(add_help=False)
CRAWLER_PARSER_GROUP = CRAWLER_PARSER.add_argument_group(
    title="general crawler arguments",
    description="arguments common to all crawlers",
)
CRAWLER_PARSER_GROUP.add_argument(
    "--redownload", "-r",
    type=show_value_error(Redownload.from_string),
    metavar="OPTION",
    help="when to download a file that's already present locally"
)
CRAWLER_PARSER_GROUP.add_argument(
    "--on-conflict",
    type=show_value_error(OnConflict.from_string),
    metavar="OPTION",
    help="what to do when local and remote files or directories differ"
)
CRAWLER_PARSER_GROUP.add_argument(
    "--transform", "-T",
    action="append",
    type=str,
    metavar="RULE",
    help="add a single transformation rule. Can be specified multiple times"
)
CRAWLER_PARSER_GROUP.add_argument(
    "--tasks", "-n",
    type=int,
    metavar="N",
    help="maximum number of concurrent tasks (crawling, downloading)"
)
CRAWLER_PARSER_GROUP.add_argument(
    "--downloads", "-N",
    type=int,
    metavar="N",
    help="maximum number of tasks that may download data at the same time"
)
CRAWLER_PARSER_GROUP.add_argument(
    "--task-delay", "-d",
    type=float,
    metavar="SECONDS",
    help="time the crawler should wait between subsequent tasks"
)
CRAWLER_PARSER_GROUP.add_argument(
    "--windows-paths",
    action=BooleanOptionalAction,
    help="whether to repair invalid paths on windows"
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
    if args.tasks is not None:
        section["tasks"] = str(args.tasks)
    if args.downloads is not None:
        section["downloads"] = str(args.downloads)
    if args.task_delay is not None:
        section["task_delay"] = str(args.task_delay)
    if args.windows_paths is not None:
        section["windows_paths"] = "yes" if args.windows_paths else "no"


PARSER = argparse.ArgumentParser()
PARSER.set_defaults(command=None)
PARSER.add_argument(
    "--version",
    action="version",
    version=f"{NAME} {VERSION} (https://github.com/Garmelon/PFERD)",
)
PARSER.add_argument(
    "--config", "-c",
    type=Path,
    metavar="PATH",
    help="custom config file"
)
PARSER.add_argument(
    "--dump-config",
    action="store_true",
    help="dump current configuration to the default config path and exit"
)
PARSER.add_argument(
    "--dump-config-to",
    metavar="PATH",
    help="dump current configuration to a file and exit."
    " Use '-' as path to print to stdout instead"
)
PARSER.add_argument(
    "--debug-transforms",
    action="store_true",
    help="apply transform rules to files of previous run"
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
    "--skip", "-S",
    action="append",
    type=str,
    metavar="NAME",
    help="don't execute this particular crawler."
    " Can be specified multiple times to skip multiple crawlers"
)
PARSER.add_argument(
    "--working-dir",
    type=Path,
    metavar="PATH",
    help="custom working directory"
)
PARSER.add_argument(
    "--explain",
    action=BooleanOptionalAction,
    help="log and explain in detail what PFERD is doing"
)
PARSER.add_argument(
    "--status",
    action=BooleanOptionalAction,
    help="print status updates while PFERD is crawling"
)
PARSER.add_argument(
    "--report",
    action=BooleanOptionalAction,
    help="print a report of all local changes before exiting"
)
PARSER.add_argument(
    "--share-cookies",
    action=BooleanOptionalAction,
    help="whether crawlers should share cookies where applicable"
)
PARSER.add_argument(
    "--show-not-deleted",
    action=BooleanOptionalAction,
    help="print messages in status and report when PFERD did not delete a local only file"
)


def load_default_section(
        args: argparse.Namespace,
        parser: configparser.ConfigParser,
) -> None:
    section = parser[parser.default_section]

    if args.working_dir is not None:
        section["working_dir"] = str(args.working_dir)
    if args.explain is not None:
        section["explain"] = "yes" if args.explain else "no"
    if args.status is not None:
        section["status"] = "yes" if args.status else "no"
    if args.report is not None:
        section["report"] = "yes" if args.report else "no"
    if args.share_cookies is not None:
        section["share_cookies"] = "yes" if args.share_cookies else "no"
    if args.show_not_deleted is not None:
        section["show_not_deleted"] = "yes" if args.show_not_deleted else "no"


SUBPARSERS = PARSER.add_subparsers(title="crawlers")
