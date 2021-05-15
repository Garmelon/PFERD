from configparser import SectionProxy
from typing import Callable, Dict

from ..authenticator import Authenticator, AuthSection
from ..conductor import TerminalConductor
from ..config import Config
from .simple import SimpleAuthenticator, SimpleAuthSection
from .tfa import TfaAuthenticator

AuthConstructor = Callable[[
    str,                # Name (without the "auth:" prefix)
    SectionProxy,       # Authenticator's section of global config
    Config,             # Global config
    TerminalConductor,  # Global conductor instance
], Authenticator]

AUTHENTICATORS: Dict[str, AuthConstructor] = {
    "simple": lambda n, s, c, t:
        SimpleAuthenticator(n, SimpleAuthSection(s), c, t),
    "tfa": lambda n, s, c, t:
        TfaAuthenticator(n, AuthSection(s), c, t),
}
