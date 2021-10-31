import subprocess
from typing import Tuple

from ..config import Config
from .authenticator import Authenticator, AuthLoadError, AuthSection


class PassAuthSection(AuthSection):
    def name(self) -> str:
        value = self.s.get("name")
        if value is None:
            self.missing_value("name")
        return value


class PassAuthenticator(Authenticator):
    def __init__(self, name: str, section: PassAuthSection, config: Config) -> None:
        super().__init__(name)

        try:
            passcontent = subprocess.run(["pass", "show", section.name()],
                                         text=True, capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError) as e:
            raise AuthLoadError("Error calling pass") from e

        lines = passcontent.splitlines()
        self._password = lines[0]
        self._username = ""

        for line in lines:
            if line.startswith('login:'):
                self._username = line.split(':')[1].strip()

        if not self._username:
            raise AuthLoadError("No username in pass")

    async def credentials(self) -> Tuple[str, str]:
        return self._username, self._password
