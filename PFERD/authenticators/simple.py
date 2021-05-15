from typing import Optional, Tuple

from ..authenticator import Authenticator, AuthException, AuthSection
from ..conductor import TerminalConductor
from ..config import Config
from ..utils import agetpass, ainput


class SimpleAuthSection(AuthSection):
    def username(self) -> Optional[str]:
        return self.s.get("username")

    def password(self) -> Optional[str]:
        return self.s.get("password")


class SimpleAuthenticator(Authenticator):
    def __init__(
            self,
            name: str,
            section: SimpleAuthSection,
            config: Config,
            conductor: TerminalConductor,
    ) -> None:
        super().__init__(name, section, config, conductor)

        self.username = section.username()
        self.password = section.password()

        self.username_fixed = self.username is not None
        self.password_fixed = self.password is not None

    async def credentials(self) -> Tuple[str, str]:
        if self.username is not None and self.password is not None:
            return self.username, self.password

        async with self.conductor.exclusive_output():
            if self.username is None:
                self.username = await ainput("Username: ")
            else:
                print(f"Username: {self.username}")

            if self.password is None:
                self.password = await agetpass("Password: ")

        return self.username, self.password

    def invalidate_credentials(self) -> None:
        if self.username_fixed and self.password_fixed:
            raise AuthException("Configured credentials are invalid")

        if not self.username_fixed:
            self.username = None
        if not self.password_fixed:
            self.password = None

    def invalidate_username(self) -> None:
        if self.username_fixed:
            raise AuthException("Configured username is invalid")
        else:
            self.username = None

    def invalidate_password(self) -> None:
        if self.password_fixed:
            raise AuthException("Configured password is invalid")
        else:
            self.password = None
