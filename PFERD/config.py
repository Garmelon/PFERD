import configparser
import os
from pathlib import Path
from typing import Optional

from .utils import prompt_yes_no


class ConfigLoadException(Exception):
    pass


class ConfigDumpException(Exception):
    pass


class Config:
    @staticmethod
    def _default_path() -> Path:
        if os.name == "posix":
            return Path("~/.config/PFERD/pferd.cfg").expanduser()
        elif os.name == "nt":
            return Path("~/AppData/Roaming/PFERD/pferd.cfg").expanduser()
        else:
            return Path("~/.pferd.cfg").expanduser()

    def __init__(self, parser: configparser.ConfigParser):
        self._parser = parser
        # TODO Load and validate config into dataclasses

    @staticmethod
    def _fail_load(path: Path, reason: str) -> None:
        print(f"Failed to load config file at {path}")
        print(f"Reason: {reason}")
        raise ConfigLoadException()

    @staticmethod
    def load_parser(path: Optional[Path] = None) -> configparser.ConfigParser:
        """
        May throw a ConfigLoadException.
        """

        if not path:
            path = Config._default_path()

        parser = configparser.ConfigParser()

        # Using config.read_file instead of config.read because config.read
        # would just ignore a missing file and carry on.
        try:
            with open(path) as f:
                parser.read_file(f, source=str(path))
        except FileNotFoundError:
            Config._fail_load(path, "File does not exist")
        except IsADirectoryError:
            Config._fail_load(path, "That's a directory, not a file")
        except PermissionError:
            Config._fail_load(path, "Insufficient permissions")

        return parser

    @staticmethod
    def _fail_dump(path: Path, reason: str) -> None:
        print(f"Failed to dump config file to {path}")
        print(f"Reason: {reason}")
        raise ConfigDumpException()

    def dump(self, path: Optional[Path] = None) -> None:
        """
        May throw a ConfigDumpException.
        """

        if not path:
            path = self._default_path()

        print(f"Dumping config to {path}")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            self._fail_dump(path, "Could not create parent directory")

        try:
            # Ensuring we don't accidentally overwrite any existing files by
            # always asking before overwriting a file.
            try:
                # x = open for exclusive creation, failing if the file already
                # exists
                with open(path, "x") as f:
                    self._parser.write(f)
            except FileExistsError:
                print("That file already exists.")
                if prompt_yes_no("Overwrite it?", default=False):
                    with open(path, "w") as f:
                        self._parser.write(f)
                else:
                    self._fail_dump(path, "File already exists")
        except IsADirectoryError:
            self._fail_dump(path, "That's a directory, not a file")
        except PermissionError:
            self._fail_dump(path, "Insufficient permissions")
