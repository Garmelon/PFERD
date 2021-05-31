from typing import Tuple

from ..logging import log
from ..utils import ainput
from .authenticator import Authenticator, AuthError


class TfaAuthenticator(Authenticator):
    def __init__(self, name: str) -> None:
        super().__init__(name)

    async def username(self) -> str:
        raise AuthError("TFA authenticator does not support usernames")

    async def password(self) -> str:
        async with log.exclusive_output():
            code = await ainput("TFA code: ")
            return code

    async def credentials(self) -> Tuple[str, str]:
        raise AuthError("TFA authenticator does not support usernames")

    def invalidate_username(self) -> None:
        raise AuthError("TFA authenticator does not support usernames")

    def invalidate_password(self) -> None:
        pass

    def invalidate_credentials(self) -> None:
        pass
