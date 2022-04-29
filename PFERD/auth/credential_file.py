from pathlib import Path
from typing import Tuple

from ..config import Config
from ..utils import fmt_real_path
from .authenticator import Authenticator, AuthLoadError, AuthSection


class CredentialFileAuthSection(AuthSection):
    def path(self) -> Path:
        value = self.s.get("path")
        if value is None:
            self.missing_value("path")
        return Path(value)


class CredentialFileAuthenticator(Authenticator):
    def __init__(self, name: str, section: CredentialFileAuthSection, config: Config) -> None:
        super().__init__(name)

        path = config.default_section.working_dir() / section.path()
        try:
            with open(path, encoding="utf-8") as f:
                lines = list(f)
        except UnicodeDecodeError:
            raise AuthLoadError(f"Credential file at {fmt_real_path(path)} is not encoded using UTF-8")
        except OSError as e:
            raise AuthLoadError(f"No credential file at {fmt_real_path(path)}") from e

        if len(lines) != 2:
            raise AuthLoadError("Credential file must be two lines long")
        [uline, pline] = lines
        uline = uline[:-1]  # Remove trailing newline
        if pline.endswith("\n"):
            pline = pline[:-1]

        if not uline.startswith("username="):
            raise AuthLoadError("First line must start with 'username='")
        if not pline.startswith("password="):
            raise AuthLoadError("Second line must start with 'password='")

        self._username = uline[9:]
        self._password = pline[9:]

    async def credentials(self) -> Tuple[str, str]:
        return self._username, self._password
