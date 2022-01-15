from configparser import SectionProxy
from typing import Callable, Dict

from ..config import Config
from .authenticator import Authenticator, AuthError, AuthLoadError, AuthSection  # noqa: F401
from .credential_file import CredentialFileAuthenticator, CredentialFileAuthSection
from .keyring import KeyringAuthenticator, KeyringAuthSection
from .pass_ import PassAuthenticator, PassAuthSection
from .simple import SimpleAuthenticator, SimpleAuthSection
from .tfa import TfaAuthenticator

AuthConstructor = Callable[[
    str,                # Name (without the "auth:" prefix)
    SectionProxy,       # Authenticator's section of global config
    Config,             # Global config
], Authenticator]

AUTHENTICATORS: Dict[str, AuthConstructor] = {
    "credential-file": lambda n, s, c:
        CredentialFileAuthenticator(n, CredentialFileAuthSection(s), c),
    "keyring": lambda n, s, c:
        KeyringAuthenticator(n, KeyringAuthSection(s)),
    "pass": lambda n, s, c:
        PassAuthenticator(n, PassAuthSection(s)),
    "simple": lambda n, s, c:
        SimpleAuthenticator(n, SimpleAuthSection(s)),
    "tfa": lambda n, s, c:
        TfaAuthenticator(n),
}
