from configparser import SectionProxy
from typing import Callable, Dict

from ..config import Config
from .authenticator import Authenticator, AuthError, AuthSection  # noqa: F401
from .keyring import KeyringAuthenticator, KeyringAuthSection
from .simple import SimpleAuthenticator, SimpleAuthSection
from .tfa import TfaAuthenticator

AuthConstructor = Callable[[
    str,                # Name (without the "auth:" prefix)
    SectionProxy,       # Authenticator's section of global config
    Config,             # Global config
], Authenticator]

AUTHENTICATORS: Dict[str, AuthConstructor] = {
    "simple": lambda n, s, c:
        SimpleAuthenticator(n, SimpleAuthSection(s)),
    "tfa": lambda n, s, c:
        TfaAuthenticator(n),
    "keyring": lambda n, s, c:
        KeyringAuthenticator(n, KeyringAuthSection(s))
}
