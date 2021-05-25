from typing import Optional, Tuple

import keyring

from ..config import Config
from ..logging import log
from ..utils import agetpass
from ..version import NAME
from .authenticator import Authenticator, AuthException, AuthSection


class KeyringAuthSection(AuthSection):
    def username(self) -> str:
        name = self.s.get("username")
        if name is None:
            self.missing_value("username")
        return name

    def keyring_name(self) -> str:
        return self.s.get("keyring_name", fallback=NAME)


class KeyringAuthenticator(Authenticator):

    def __init__(
            self,
            name: str,
            section: KeyringAuthSection,
            config: Config,
    ) -> None:
        super().__init__(name, section, config)

        self._username = section.username()
        self._password: Optional[str] = None
        self._keyring_name = section.keyring_name()

    async def credentials(self) -> Tuple[str, str]:
        if self._password is not None:
            return self._username, self._password

        password = keyring.get_password(self._keyring_name, self._username)

        if not password:
            async with log.exclusive_output():
                password = await agetpass("Password: ")
                keyring.set_password(self._keyring_name, self._username, password)

        self._password = password

        return self._username, password

    def invalidate_credentials(self) -> None:
        self.invalidate_password()

    def invalidate_password(self) -> None:
        raise AuthException("Invalid password")
