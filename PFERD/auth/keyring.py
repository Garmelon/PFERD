from typing import Optional, Tuple, cast

import keyring

from ..logging import log
from ..utils import agetpass, ainput
from ..version import NAME
from .authenticator import Authenticator, AuthError, AuthSection


class KeyringAuthSection(AuthSection):
    def username(self) -> Optional[str]:
        return self.s.get("username")

    def keyring_name(self) -> str:
        return cast(str, self.s.get("keyring_name", fallback=NAME))


class KeyringAuthenticator(Authenticator):

    def __init__(self, name: str, section: KeyringAuthSection) -> None:
        super().__init__(name)

        self._username = section.username()
        self._password: Optional[str] = None
        self._keyring_name = section.keyring_name()

        self._password_invalidated = False
        self._username_fixed = section.username() is not None

    async def credentials(self) -> Tuple[str, str]:
        # Request the username
        if self._username is None:
            async with log.exclusive_output():
                self._username = await ainput("Username: ")

        # First try looking it up in the keyring.
        # Do not look it up if it was invalidated - we want to re-prompt in this case
        if self._password is None and not self._password_invalidated:
            self._password = keyring.get_password(self._keyring_name, self._username)

        # If that fails it wasn't saved in the keyring - we need to
        # read it from the user and store it
        if self._password is None:
            async with log.exclusive_output():
                self._password = await agetpass("Password: ")
                keyring.set_password(self._keyring_name, self._username, self._password)

        self._password_invalidated = False
        return self._username, self._password

    def invalidate_credentials(self) -> None:
        if not self._username_fixed:
            self.invalidate_username()
        self.invalidate_password()

    def invalidate_username(self) -> None:
        if self._username_fixed:
            raise AuthError("Configured username is invalid")
        else:
            self._username = None

    def invalidate_password(self) -> None:
        self._password = None
        self._password_invalidated = True
