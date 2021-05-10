from abc import ABC, abstractmethod
from typing import Tuple

from .conductor import TerminalConductor
from .config import Config, Section


class AuthLoadException(Exception):
    pass


class AuthException(Exception):
    pass


class AuthSection(Section):
    pass


class Authenticator(ABC):
    def __init__(
            self,
            name: str,
            section: AuthSection,
            config: Config,
            conductor: TerminalConductor,
    ) -> None:
        """
        Initialize an authenticator from its name and its section in the config
        file.

        If you are writing your own constructor for your own authenticator,
        make sure to call this constructor first (via super().__init__).

        May throw an AuthLoadException.
        """

        self.name = name
        self.conductor = conductor

    @abstractmethod
    async def credentials(self) -> Tuple[str, str]:
        pass

    def invalid_credentials(self) -> None:
        raise AuthException("Invalid credentials")

    def invalid_username(self) -> None:
        raise AuthException("Invalid username")

    def invalid_password(self) -> None:
        raise AuthException("Invalid password")
