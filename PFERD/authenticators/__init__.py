from configparser import SectionProxy
from typing import Callable, Dict

from ..authenticator import Authenticator, AuthSection
from ..config import Config
from .simple import SimpleAuthenticator, SimpleAuthSection
from .tfa import TfaAuthenticator

AuthConstructor = Callable[[
    str,                # Name (without the "auth:" prefix)
    SectionProxy,       # Authenticator's section of global config
    Config,             # Global config
], Authenticator]

AUTHENTICATORS: Dict[str, AuthConstructor] = {
    "simple": lambda n, s, c:
        SimpleAuthenticator(n, SimpleAuthSection(s), c),
    "tfa": lambda n, s, c:
        TfaAuthenticator(n, AuthSection(s), c),
}
