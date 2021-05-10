from configparser import SectionProxy
from typing import Callable, Dict

from ..authenticator import Authenticator
from ..conductor import TerminalConductor
from ..config import Config
from .simple import SimpleAuthenticator, SimpleAuthSection

AuthConstructor = Callable[[
    str,                # Name (without the "auth:" prefix)
    SectionProxy,       # Authenticator's section of global config
    Config,             # Global config
    TerminalConductor,  # Global conductor instance
], Authenticator]

AUTHENTICATORS: Dict[str, AuthConstructor] = {
    "simple": lambda n, s, c, t:
        SimpleAuthenticator(n, SimpleAuthSection(s), c, t),
}
