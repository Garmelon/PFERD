import re
import subprocess
from typing import List, Tuple

from ..logging import log
from .authenticator import Authenticator, AuthError, AuthSection


class PassAuthSection(AuthSection):
    def passname(self) -> str:
        if (value := self.s.get("passname")) is None:
            self.missing_value("passname")
        return value

    def username_prefixes(self) -> List[str]:
        value = self.s.get("username_prefixes", "login,username,user")
        return [prefix.lower() for prefix in value.split(",")]

    def password_prefixes(self) -> List[str]:
        value = self.s.get("password_prefixes", "password,pass,secret")
        return [prefix.lower() for prefix in value.split(",")]


class PassAuthenticator(Authenticator):
    PREFIXED_LINE_RE = r"([a-zA-Z]+):\s?(.*)"  # to be used with fullmatch

    def __init__(self, name: str, section: PassAuthSection) -> None:
        super().__init__(name)

        self._passname = section.passname()
        self._username_prefixes = section.username_prefixes()
        self._password_prefixes = section.password_prefixes()

    async def credentials(self) -> Tuple[str, str]:
        log.explain_topic("Obtaining credentials from pass")

        try:
            log.explain(f"Calling 'pass show {self._passname}'")
            result = subprocess.check_output(["pass", "show", self._passname], text=True)
        except subprocess.CalledProcessError as e:
            raise AuthError(f"Failed to get password info from {self._passname}: {e}")

        prefixed = {}
        unprefixed = []
        for line in result.strip().splitlines():
            if match := re.fullmatch(self.PREFIXED_LINE_RE, line):
                prefix = match.group(1).lower()
                value = match.group(2)
                log.explain(f"Found prefixed line {line!r} with prefix {prefix!r}, value {value!r}")
                if prefix in prefixed:
                    raise AuthError(f"Prefix {prefix} specified multiple times")
                prefixed[prefix] = value
            else:
                log.explain(f"Found unprefixed line {line!r}")
                unprefixed.append(line)

        username = None
        for prefix in self._username_prefixes:
            log.explain(f"Looking for username at prefix {prefix!r}")
            if prefix in prefixed:
                username = prefixed[prefix]
                log.explain(f"Found username {username!r}")
                break

        password = None
        for prefix in self._password_prefixes:
            log.explain(f"Looking for password at prefix {prefix!r}")
            if prefix in prefixed:
                password = prefixed[prefix]
                log.explain(f"Found password {password!r}")
                break

        if password is None and username is None:
            log.explain("No username and password found so far")
            log.explain("Using first unprefixed line as password")
            log.explain("Using second unprefixed line as username")
        elif password is None:
            log.explain("No password found so far")
            log.explain("Using first unprefixed line as password")
        elif username is None:
            log.explain("No username found so far")
            log.explain("Using first unprefixed line as username")

        if password is None:
            if not unprefixed:
                log.explain("Not enough unprefixed lines left")
                raise AuthError("Password could not be determined")
            password = unprefixed.pop(0)
            log.explain(f"Found password {password!r}")

        if username is None:
            if not unprefixed:
                log.explain("Not enough unprefixed lines left")
                raise AuthError("Username could not be determined")
            username = unprefixed.pop(0)
            log.explain(f"Found username {username!r}")

        return username, password
