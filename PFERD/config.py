import asyncio
import os
import sys
from configparser import ConfigParser, SectionProxy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, NoReturn, Optional, Tuple

from .logging import log
from .utils import prompt_yes_no


@dataclass
class ConfigLoadException(Exception):
    path: Path
    reason: str


class ConfigDumpException(Exception):
    pass


@dataclass
class ConfigFormatException(Exception):
    section: str
    key: str
    desc: str


class Section:
    """
    Base class for the crawler and auth section classes.
    """

    def __init__(self, section: SectionProxy):
        self.s = section

    def error(self, key: str, desc: str) -> NoReturn:
        raise ConfigFormatException(self.s.name, key, desc)

    def invalid_value(
            self,
            key: str,
            value: Any,
            reason: Optional[str],
    ) -> NoReturn:
        if reason is None:
            self.error(key, f"Invalid value {value!r}")
        else:
            self.error(key, f"Invalid value {value!r}: {reason}")

    def missing_value(self, key: str) -> NoReturn:
        self.error(key, "Missing value")


class DefaultSection(Section):
    def working_dir(self) -> Path:
        pathstr = self.s.get("working_dir", ".")
        return Path(pathstr).expanduser()

    def explain(self) -> bool:
        return self.s.getboolean("explain", fallback=False)


class Config:
    @staticmethod
    def _default_path() -> Path:
        if os.name == "posix":
            return Path("~/.config/PFERD/pferd.cfg").expanduser()
        elif os.name == "nt":
            return Path("~/AppData/Roaming/PFERD/pferd.cfg").expanduser()
        else:
            return Path("~/.pferd.cfg").expanduser()

    def __init__(self, parser: ConfigParser):
        self._parser = parser
        self._default_section = DefaultSection(parser[parser.default_section])

    @property
    def default_section(self) -> DefaultSection:
        return self._default_section

    @staticmethod
    def load_parser(parser: ConfigParser, path: Optional[Path] = None) -> None:
        """
        May throw a ConfigLoadException.
        """

        if path:
            log.explain("Using custom path")
        else:
            log.explain("Using default path")
            path = Config._default_path()
        log.explain(f"Loading {str(path)!r}")

        # Using config.read_file instead of config.read because config.read
        # would just ignore a missing file and carry on.
        try:
            with open(path) as f:
                parser.read_file(f, source=str(path))
        except FileNotFoundError:
            raise ConfigLoadException(path, "File does not exist")
        except IsADirectoryError:
            raise ConfigLoadException(path, "That's a directory, not a file")
        except PermissionError:
            raise ConfigLoadException(path, "Insufficient permissions")

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
                if asyncio.run(prompt_yes_no("Overwrite it?", default=False)):
                    with open(path, "w") as f:
                        self._parser.write(f)
                else:
                    self._fail_dump(path, "File already exists")
        except IsADirectoryError:
            self._fail_dump(path, "That's a directory, not a file")
        except PermissionError:
            self._fail_dump(path, "Insufficient permissions")

    def dump_to_stdout(self) -> None:
        self._parser.write(sys.stdout)

    def crawler_sections(self) -> List[Tuple[str, SectionProxy]]:
        result = []
        for name, proxy in self._parser.items():
            if name.startswith("crawl:"):
                result.append((name, proxy))

        return result

    def authenticator_sections(self) -> List[Tuple[str, SectionProxy]]:
        result = []
        for name, proxy in self._parser.items():
            if name.startswith("auth:"):
                result.append((name, proxy))

        return result
