from typing import Tuple

from ..config import Config
from ..logging import log
from ..utils import ainput
from .authenticator import Authenticator, AuthException, AuthSection


class TfaAuthenticator(Authenticator):
    def __init__(
            self,
            name: str,
            section: AuthSection,
            config: Config,
    ) -> None:
        super().__init__(name, section, config)

    async def username(self) -> str:
        raise AuthException("TFA authenticator does not support usernames")

    async def password(self) -> str:
        async with log.exclusive_output():
            code = await ainput("TFA code: ")
            return code

    async def credentials(self) -> Tuple[str, str]:
        raise AuthException("TFA authenticator does not support usernames")

    def invalidate_username(self) -> None:
        raise AuthException("TFA authenticator does not support usernames")

    def invalidate_password(self) -> None:
        pass

    def invalidate_credentials(self) -> None:
        pass
