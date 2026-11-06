# SPDX-License-Identifier: Apache-2.0
"""Redaction of tool outputs (spec 011, FR-009, FR-010; research R6)."""

import json

import pytest

from opscout.services.redact import redact, redact_structure

KEEP_ALL = frozenset({"account-id", "ip", "email"})
SECRET_SHAPED = "Ab3" * 12  # 36 characters, letters and digits: secret-like


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


@spec("FR-009")
@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----", "private-key"),
        ("postgres://app:hunter2pass@db.example.com:5432/app", "connection-string"),
        ("key AKIAEXAMPLEEXAMPLE12 in use", "credential"),
        ("DB_PASSWORD=hunter2", "credential"),
        (f"value {SECRET_SHAPED} here", "secret-like"),
        ("call +1 202 555 0143 now", "phone"),
    ],
)
def test_secrets_and_phones_are_always_redacted(text: str, kind: str) -> None:
    redacted, counts = redact(text, keep=KEEP_ALL)

    assert counts.get(kind) == 1, (redacted, counts)
    assert "hunter2" not in redacted
    assert SECRET_SHAPED not in redacted


@spec("FR-010")
def test_account_ids_ips_and_emails_are_kept_unless_redaction_is_on() -> None:
    text = "account 123456789012 from 192.0.2.10 by ops@example.com"

    assert redact(text, keep=KEEP_ALL) == (text, {})
    redacted, counts = redact(text, keep=frozenset({"ip"}))
    assert redacted == "account [account-id] from 192.0.2.10 by [email]"
    assert counts == {"account-id": 1, "email": 1}


@spec("FR-010")
def test_spec_009s_default_still_redacts_everything() -> None:
    redacted, counts = redact("account 123456789012 from 192.0.2.10 by ops@example.com")

    assert redacted == "account [account-id] from [ip] by [email]"
    assert counts == {"account-id": 1, "ip": 1, "email": 1}


@spec("FR-009")
def test_every_string_leaf_is_redacted_and_the_result_stays_json() -> None:
    value = {
        "rows": [
            {"message": 'connecting to "mysql://root:toor99@db.example.com/x"'},
            {"message": "fine", "count": 3, "ok": True, "none": None},
        ],
        "nested": [["AKIAEXAMPLEEXAMPLE12"]],
    }

    redacted, counts = redact_structure(value, KEEP_ALL)

    text = json.dumps(redacted)
    assert "toor99" not in text
    assert "AKIAEXAMPLEEXAMPLE12" not in text
    assert redacted["rows"][1] == {"message": "fine", "count": 3, "ok": True, "none": None}
    assert counts == {"connection-string": 1, "credential": 1}
    assert json.loads(text) == redacted


@spec("FR-009")
def test_a_secret_named_key_hides_its_value_whatever_its_type() -> None:
    value = {
        "DbPassword": "plain",
        "api_key": 12345,
        "Config": {"client_secret": ["a", "b"], "Name": "kept"},
    }

    redacted, counts = redact_structure(value, KEEP_ALL)

    assert redacted == {
        "DbPassword": "[secret]",
        "api_key": "[secret]",
        "Config": {"client_secret": "[secret]", "Name": "kept"},
    }
    assert counts == {"secret": 3}


@spec("FR-009")
@pytest.mark.parametrize(
    ("pair", "name_field", "value_field"),
    [
        ({"Key": "ApiToken", "Value": "plain-1"}, "Key", "Value"),
        (
            {"ParameterKey": "DbPassword", "ParameterValue": "plain-2"},
            "ParameterKey",
            "ParameterValue",
        ),
        ({"OutputKey": "ServiceSecret", "OutputValue": "plain-3"}, "OutputKey", "OutputValue"),
        ({"Name": "private_key", "Value": "plain-4"}, "Name", "Value"),
    ],
)
def test_a_secret_named_pair_hides_its_value(
    pair: dict[str, str], name_field: str, value_field: str
) -> None:
    redacted, counts = redact_structure({"tags": [pair, {"Key": "Team", "Value": "ops"}]}, KEEP_ALL)

    assert redacted["tags"][0] == {name_field: pair[name_field], value_field: "[secret]"}
    assert redacted["tags"][1] == {"Key": "Team", "Value": "ops"}
    assert counts == {"secret": 1}
