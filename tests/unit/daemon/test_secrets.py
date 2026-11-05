# SPDX-License-Identifier: Apache-2.0
"""KeyringSecretStore on an in-memory keyring backend (spec 007, US4, FR-023)."""

from collections.abc import Iterator

import keyring
import keyring.errors
import pytest
from keyring.backend import KeyringBackend

from opscout.adapters.keychain import KeyringSecretStore
from opscout.core.config import KeychainRef
from opscout.core.daemon import SecretError, SecretStatus
from tests.unit.daemon.fakes import SENTINEL


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 007."""
    return pytest.mark.spec("007", requirement)


class MemoryKeyring(KeyringBackend):
    """A keyring backend in memory; ``locked`` makes every call fail."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.values: dict[tuple[str, str], str] = {}
        self.locked = False

    def get_password(self, service: str, username: str) -> str | None:
        if self.locked:
            raise keyring.errors.KeyringLocked("the keychain is locked")
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        if self.locked:
            raise keyring.errors.PasswordSetError("the keychain is locked")
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


@pytest.fixture
def backend() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    memory = MemoryKeyring()
    keyring.set_keyring(memory)
    yield memory
    keyring.set_keyring(previous)


REF = KeychainRef(service="opscout-example")


@spec("FR-023")
def test_store_then_resolve_under_the_default_account(backend: MemoryKeyring) -> None:
    store = KeyringSecretStore()
    assert store.status("claude_token", REF) == SecretStatus("missing")
    store.store("claude_token", REF, SENTINEL)
    assert backend.values == {("opscout-example", "opscout"): SENTINEL}
    assert store.status("claude_token", REF) == SecretStatus("present")
    assert store.resolve("claude_token", REF) == SENTINEL
    account = KeychainRef(service="opscout-example", account="example")
    assert store.status("claude_token", account) == SecretStatus("missing")


@spec("FR-023")
def test_missing_and_unavailable_are_told_apart(backend: MemoryKeyring) -> None:
    store = KeyringSecretStore()
    with pytest.raises(SecretError, match="opscout secret set claude_token") as missing:
        store.resolve("claude_token", REF)
    assert missing.value.status.state == "missing"
    backend.locked = True
    assert store.status("claude_token", REF) == SecretStatus("unavailable", "KeyringLocked")
    with pytest.raises(SecretError, match="unavailable") as locked:
        store.resolve("claude_token", REF)
    assert SENTINEL not in str(locked.value)
    with pytest.raises(SecretError):
        store.store("claude_token", REF, SENTINEL)


@spec("FR-023")
def test_no_backend_is_unavailable(backend: MemoryKeyring, monkeypatch: pytest.MonkeyPatch) -> None:
    def none(service: str, username: str) -> str | None:
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", none)
    assert KeyringSecretStore().status("claude_token", REF).state == "unavailable"
