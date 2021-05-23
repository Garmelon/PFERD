from abc import ABC, abstractmethod
from typing import Tuple

from ..config import Config, Section


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
    ) -> None:
        """
        Initialize an authenticator from its name and its section in the config
        file.

        If you are writing your own constructor for your own authenticator,
        make sure to call this constructor first (via super().__init__).

        May throw an AuthLoadException.
        """

        self.name = name

    @abstractmethod
    async def credentials(self) -> Tuple[str, str]:
        pass

    async def username(self) -> str:
        username, _ = await self.credentials()
        return username

    async def password(self) -> str:
        _, password = await self.credentials()
        return password

    def invalidate_credentials(self) -> None:
        """
        Tell the authenticator that some or all of its credentials are invalid.

        Authenticators should overwrite this function if they have a way to
        deal with this issue that is likely to result in valid credentials
        (e. g. prompting the user).
        """

        raise AuthException("Invalid credentials")

    def invalidate_username(self) -> None:
        """
        Tell the authenticator that specifically its username is invalid.

        Authenticators should overwrite this function if they have a way to
        deal with this issue that is likely to result in valid credentials
        (e. g. prompting the user).
        """

        raise AuthException("Invalid username")

    def invalidate_password(self) -> None:
        """
        Tell the authenticator that specifically its password is invalid.

        Authenticators should overwrite this function if they have a way to
        deal with this issue that is likely to result in valid credentials
        (e. g. prompting the user).
        """

        raise AuthException("Invalid password")
