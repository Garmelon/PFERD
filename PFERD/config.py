import asyncio
import os
import sys
from configparser import ConfigParser, SectionProxy
from pathlib import Path
from typing import Any, List, NoReturn, Optional, Tuple

from rich.markup import escape

from .logging import log
from .utils import fmt_real_path, prompt_yes_no


class ConfigLoadError(Exception):
    """
    Something went wrong while loading the config from a file.
    """

    def __init__(self, path: Path, reason: str):
        super().__init__(f"Failed to load config from {fmt_real_path(path)}")
        self.path = path
        self.reason = reason


class ConfigOptionError(Exception):
    """
    An option in the config file has an invalid or missing value.
    """

    def __init__(self, section: str, key: str, desc: str):
        super().__init__(f"Section {section!r}, key {key!r}: {desc}")
        self.section = section
        self.key = key
        self.desc = desc


class ConfigDumpError(Exception):
    def __init__(self, path: Path, reason: str):
        super().__init__(f"Failed to dump config to {fmt_real_path(path)}")
        self.path = path
        self.reason = reason


class Section:
    """
    Base class for the crawler and auth section classes.
    """

    def __init__(self, section: SectionProxy):
        self.s = section

    def error(self, key: str, desc: str) -> NoReturn:
        raise ConfigOptionError(self.s.name, key, desc)

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
        # TODO Change to working dir instead of manually prepending it to paths
        pathstr = self.s.get("working_dir", ".")
        return Path(pathstr).expanduser()

    def explain(self) -> bool:
        return self.s.getboolean("explain", fallback=False)

    def status(self) -> bool:
        return self.s.getboolean("status", fallback=True)

    def report(self) -> bool:
        return self.s.getboolean("report", fallback=True)

    def show_not_deleted(self) -> bool:
        return self.s.getboolean("show_not_deleted", fallback=True)

    def share_cookies(self) -> bool:
        return self.s.getboolean("share_cookies", fallback=True)


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
        May throw a ConfigLoadError.
        """

        if path:
            log.explain("Path specified on CLI")
        else:
            log.explain("Using default path")
            path = Config._default_path()
        log.explain(f"Loading {fmt_real_path(path)}")

        # Using config.read_file instead of config.read because config.read
        # would just ignore a missing file and carry on.
        try:
            with open(path, encoding="utf-8") as f:
                parser.read_file(f, source=str(path))
        except FileNotFoundError:
            raise ConfigLoadError(path, "File does not exist")
        except IsADirectoryError:
            raise ConfigLoadError(path, "That's a directory, not a file")
        except PermissionError:
            raise ConfigLoadError(path, "Insufficient permissions")
        except UnicodeDecodeError:
            raise ConfigLoadError(path, "File is not encoded using UTF-8")

    def dump(self, path: Optional[Path] = None) -> None:
        """
        May throw a ConfigDumpError.
        """

        if path:
            log.explain("Using custom path")
        else:
            log.explain("Using default path")
            path = self._default_path()

        log.explain(f"Dumping to {fmt_real_path(path)}")
        log.print(f"[bold bright_cyan]Dumping[/] to {escape(fmt_real_path(path))}")

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise ConfigDumpError(path, "Could not create parent directory")

        try:
            # Ensuring we don't accidentally overwrite any existing files by
            # always asking before overwriting a file.
            try:
                # x = open for exclusive creation, failing if the file already
                # exists
                with open(path, "x", encoding="utf-8") as f:
                    self._parser.write(f)
            except FileExistsError:
                print("That file already exists.")
                if asyncio.run(prompt_yes_no("Overwrite it?", default=False)):
                    with open(path, "w", encoding="utf-8") as f:
                        self._parser.write(f)
                else:
                    raise ConfigDumpError(path, "File already exists")
        except IsADirectoryError:
            raise ConfigDumpError(path, "That's a directory, not a file")
        except PermissionError:
            raise ConfigDumpError(path, "Insufficient permissions")

    def dump_to_stdout(self) -> None:
        self._parser.write(sys.stdout)

    def crawl_sections(self) -> List[Tuple[str, SectionProxy]]:
        result = []
        for name, proxy in self._parser.items():
            if name.startswith("crawl:"):
                result.append((name, proxy))

        return result

    def auth_sections(self) -> List[Tuple[str, SectionProxy]]:
        result = []
        for name, proxy in self._parser.items():
            if name.startswith("auth:"):
                result.append((name, proxy))

        return result
