# SPDX-License-Identifier: Apache-2.0
"""Redaction before anything reaches the model (spec 009, FR-009; research R6).

Every planted value below is fake; the corpus plants each kind in each kind of text.
"""

import pytest

from opscout.services.redact import redact

PLANTED = {
    "private-key": (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEexampleexample\n-----END RSA PRIVATE KEY-----"
    ),
    "credential": "AKIAEXAMPLEEXAMPLE12",
    "slack": "xoxb-0000000000-example-example",
    "github": "ghp_exampleexampleexampleexampleexamp1",
    # Built from parts, so no secret scanner mistakes the fake for a real one.
    "jwt": ".".join(["eyJ" + "hbGciOiJIUzI1NiJ9", "eyJ" + "zdWIiOiJleGFtcGxlIn0", "c2lnbmF0dXJl"]),
    "assignment": "password=hunter2-example",
    "connection-string": "postgres://example:s3cr3t-example@db.example.com:5432/app",
    "email": "jane.doe@example.com",
    "phone": "+1 (555) 010-0199",
    "account-id": "123456789012",
    "ip": "192.0.2.44",
    "deny-listed": "Example Corp",
    "secret-like": "Zm9vYmFy" + "YmF6cXV4" + "ZXhhbXBsZWV4YW1wbGVleGFtcGxl",
}
KINDS = {
    "private-key": "private-key",
    "credential": "credential",
    "slack": "credential",
    "github": "credential",
    "jwt": "credential",
    "assignment": "credential",
    "connection-string": "connection-string",
    "email": "email",
    "phone": "phone",
    "account-id": "account-id",
    "ip": "ip",
    "deny-listed": "deny-listed",
    "secret-like": "secret-like",
}
DENY = ["Example Corp"]


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 009."""
    return pytest.mark.spec("009", requirement)


@spec("FR-009")
@pytest.mark.parametrize("name", sorted(PLANTED))
@pytest.mark.parametrize(
    "template",
    [
        "Fix the deploy, it uses {value} today",  # a prompt
        "Rotate {value}",  # a commit subject
        "WIP: {value} in config",  # a pull request title
        "feature/{value}",  # a branch
    ],
)
def test_every_kind_is_replaced_by_its_marker(name: str, template: str) -> None:
    value = PLANTED[name]
    text, counts = redact(template.format(value=value), DENY)
    assert value not in text
    for part in value.split():
        if len(part) >= 6 and part not in ("PRIVATE", "-----BEGIN", "-----END"):
            assert part not in text, part
    assert f"[{KINDS[name]}]" in text
    assert counts[KINDS[name]] >= 1


@spec("FR-009")
def test_deny_listed_terms_any_case_even_inside_a_word() -> None:
    text, counts = redact("Ticket for example corp, in ExampleCorpApi", DENY)
    assert text == "Ticket for [deny-listed], in [deny-listed]Api"
    assert counts == {"deny-listed": 2}
    glued, counts = redact("feature/examplecorp_import", ["ExampleCorp"])
    assert glued == "feature/[deny-listed]_import"
    assert counts == {"deny-listed": 1}


@spec("FR-009")
@pytest.mark.parametrize(
    "harmless",
    [
        "Bump version to 2.14.3 and update the changelog",
        "Release on 2026-11-05 at 09:45",
        "Merge commit 1a2b3c4 into main",
        "Edit src/opscout/services/standup.py line 120",
        "PR #42: retry export job (3 tries, 500 ms)",
        "Fix the 5xx rate on example-api",
        "Ticket EXAMPLE-123 in progress",
    ],
)
def test_ordinary_text_is_left_alone(harmless: str) -> None:
    assert redact(harmless, DENY) == (harmless, {})


@spec("FR-009")
@pytest.mark.parametrize(
    "text",
    ["Account: 123456789012Threshold", "arn:aws:iam::123456789012:role/x", "id_123456789012"],
)
def test_an_account_id_glued_to_text_is_still_replaced(text: str) -> None:
    redacted, counts = redact(text, [])
    assert "123456789012" not in redacted
    assert counts.get("account-id") == 1
