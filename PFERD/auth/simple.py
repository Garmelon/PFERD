from typing import Optional, Tuple

from ..logging import log
from ..utils import agetpass, ainput
from .authenticator import Authenticator, AuthError, AuthSection


class SimpleAuthSection(AuthSection):
    def username(self) -> Optional[str]:
        return self.s.get("username")

    def password(self) -> Optional[str]:
        return self.s.get("password")


class SimpleAuthenticator(Authenticator):
    def __init__(self, name: str, section: SimpleAuthSection) -> None:
        super().__init__(name)

        self._username = section.username()
        self._password = section.password()

        self._username_fixed = self.username is not None
        self._password_fixed = self.password is not None

    async def credentials(self) -> Tuple[str, str]:
        if self._username is not None and self._password is not None:
            return self._username, self._password

        async with log.exclusive_output():
            if self._username is None:
                self._username = await ainput("Username: ")
            else:
                print(f"Username: {self._username}")

            if self._password is None:
                self._password = await agetpass("Password: ")

            # Intentionally returned inside the context manager so we know
            # they're both not None
            return self._username, self._password

    def invalidate_credentials(self) -> None:
        if self._username_fixed and self._password_fixed:
            raise AuthError("Configured credentials are invalid")

        if not self._username_fixed:
            self._username = None
        if not self._password_fixed:
            self._password = None

    def invalidate_username(self) -> None:
        if self._username_fixed:
            raise AuthError("Configured username is invalid")
        else:
            self._username = None

    def invalidate_password(self) -> None:
        if self._password_fixed:
            raise AuthError("Configured password is invalid")
        else:
            self._password = None
