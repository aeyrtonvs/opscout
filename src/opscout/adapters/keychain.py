# SPDX-License-Identifier: Apache-2.0
"""KeyringSecretStore: the harness's own secrets in the OS keychain (spec 007, research R9).

``keyring`` reaches the macOS Keychain, the freedesktop Secret Service or the Windows
Credential Locker. A missing item and an unusable keychain are told apart; errors name the
exception's type, never a value.
"""

from typing import Final

import keyring
import keyring.errors

from opscout.core.config import KeychainRef
from opscout.core.daemon import SecretError, SecretStatus

DEFAULT_ACCOUNT: Final = "opscout"


class KeyringSecretStore:
    """The ``SecretStore`` port on ``keyring``."""

    def status(self, name: str, ref: KeychainRef) -> SecretStatus:
        """Return whether the secret is there, without returning it."""
        try:
            value = keyring.get_password(ref.service, ref.account or DEFAULT_ACCOUNT)
        except keyring.errors.KeyringError as error:
            return SecretStatus("unavailable", type(error).__name__)
        return SecretStatus("missing" if value is None else "present")

    def resolve(self, name: str, ref: KeychainRef) -> str:
        """Return the value. Raises ``SecretError``."""
        try:
            value = keyring.get_password(ref.service, ref.account or DEFAULT_ACCOUNT)
        except keyring.errors.KeyringError as error:
            raise SecretError(name, SecretStatus("unavailable", type(error).__name__)) from None
        if value is None:
            raise SecretError(name, SecretStatus("missing"))
        return value

    def store(self, name: str, ref: KeychainRef, value: str) -> None:
        """Store the value. Raises ``SecretError``."""
        try:
            keyring.set_password(ref.service, ref.account or DEFAULT_ACCOUNT, value)
        except keyring.errors.KeyringError as error:
            raise SecretError(name, SecretStatus("unavailable", type(error).__name__)) from None
