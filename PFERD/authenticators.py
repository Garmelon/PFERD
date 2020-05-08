"""
General authenticators useful in many situations
"""

import getpass
from typing import Optional, Tuple


class TfaAuthenticator:
    # pylint: disable=too-few-public-methods
    """
    An authenticator for a TFA token. Always prompts the user, as the token can not be cached.
    """

    def __init__(self, reason: str):
        """
        Create a new tfa authenticator.

        Arguments:
            reason {str} -- the reason for obtaining the credentials
        """
        self._reason = reason

    def get_token(self) -> str:
        # pylint: disable=no-self-use
        """
        Prompts the user for the token and returns it.
        """
        print(f"Enter credentials ({self._reason})")
        return getpass.getpass("TFA Token: ")


class UserPassAuthenticator:
    """
    An authenticator for username-password combinations that prompts the user
    for missing information.
    """

    def __init__(
            self,
            reason: str,
            username: Optional[str] = None,
            password: Optional[str] = None,
    ) -> None:
        """
        reason   - what the credentials are used for
        username - the username (if already known)
        password - the password (if already known)
        """

        self._reason = reason

        self._given_username = username
        self._given_password = password

        self._username = username
        self._password = password

    def get_credentials(self) -> Tuple[str, str]:
        """
        Returns a tuple (username, password). Prompts user for username or
        password when necessary.
        """

        if self._username is None and self._given_username is not None:
            self._username = self._given_username

        if self._password is None and self._given_password is not None:
            self._password = self._given_password

        if self._username is None or self._password is None:
            print(f"Enter credentials ({self._reason})")

        username: str
        if self._username is None:
            username = input("Username: ")
            self._username = username
        else:
            username = self._username

        password: str
        if self._password is None:
            password = getpass.getpass(prompt="Password: ")
            self._password = password
        else:
            password = self._password

        return (username, password)

    @property
    def username(self) -> str:
        """
        The username. Accessing this property may cause the authenticator to
        prompt the user.
        """

        (username, _) = self.get_credentials()
        return username

    @property
    def password(self) -> str:
        """
        The password. Accessing this property may cause the authenticator to
        prompt the user.
        """

        (_, password) = self.get_credentials()
        return password

    def invalidate_credentials(self) -> None:
        """
        Marks the credentials as invalid. If only a username was supplied in
        the constructor, assumes that the username is valid and only the
        password is invalid. If only a password was supplied in the
        constructor, assumes that the password is valid and only the username
        is invalid. Otherwise, assumes that username and password are both
        invalid.
        """

        self._username = None
        self._password = None

        if self._given_username is not None and self._given_password is not None:
            self._given_username = None
            self._given_password = None
