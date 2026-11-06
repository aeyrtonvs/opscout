# SPDX-License-Identifier: Apache-2.0
"""The identity's reference documentation matches the package (spec 010, FR-017-FR-019)."""

import re
from pathlib import Path

import pytest

from opscout.adapters.identity_files import load_records, reference_files
from opscout.core.identity import Records

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "reference" / "identity.md"
SAFE_PROBES = re.compile(
    r"^(aws iam simulate-principal-policy --policy-source-arn \S+ --action-names [\w:\s-]+"
    r"|aws secretsmanager get-secret-value --secret-id opscout-probe-does-not-exist"
    r"|aws ssm get-parameter --name /opscout/probe-does-not-exist --with-decryption"
    r"|aws ec2 (create-tags|run-instances) --dry-run [^#]+"
    r"|aws ssm start-session --target i-0123456789abcdef0"
    r"|aws ssm send-command --document-name AWS-RunShellScript --instance-ids "
    r"i-0123456789abcdef0 --parameters commands=id"
    r"|kubectl auth can-i (get|create|--list)[^#]*)  # expect: "
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


@pytest.fixture(scope="module")
def records() -> Records:
    return load_records()


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _section(title: str) -> str:
    return _text().split(f"## {title}\n", 1)[1].split("\n## ", 1)[0]


@spec("FR-017")
def test_the_capabilities_table_equals_the_declarations(records: Records) -> None:
    rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in _section("Capabilities").splitlines()
        if line.startswith("| ") and not line.startswith("| Capability")
    ]
    assert [row[0] for row in rows] == [c.name for c in records.capabilities]
    for row, capability in zip(rows, records.capabilities, strict=True):
        assert row[1] == capability.identity
        assert row[2] == ("yes" if capability.optional else "no")
        assert row[3] == ", ".join(capability.agents)
        assert re.findall(r"`([^`]+)`", row[4]) == (
            ["ViewOnlyAccess"] if capability.grant == "managed" else list(capability.actions)
        )
        assert row[5] == capability.purpose


@spec("FR-017")
def test_every_reference_file_is_named_and_the_engine_applies_nothing() -> None:
    text = _text()

    for path, _ in reference_files():
        assert f"`{path}`" in text, path
    assert "never applies" in text
    assert "aws_ssoadmin_permissions_boundary_attachment" in text
    assert 'permissions_boundary = "arn:aws:iam::aws:policy/ReadOnlyAccess"' in text


@spec("FR-018")
def test_every_live_probe_cannot_change_anything_and_states_its_outcome() -> None:
    probes = [
        line
        for block in re.findall(r"```sh\n(.*?)```", _section("Live check"), re.S)
        for line in block.splitlines()
        if line.strip()
    ]
    assert len(probes) >= 12
    for probe in probes:
        assert SAFE_PROBES.match(probe), probe


@spec("FR-019")
def test_credentials_for_the_four_systems_are_read_only() -> None:
    section = _section("Credentials for other systems")
    standup = (REPO_ROOT / "docs" / "reference" / "standup.md").read_text(encoding="utf-8")
    daemon = (REPO_ROOT / "docs" / "reference" / "daemon.md").read_text(encoding="utf-8")
    rows = {
        line.split("|")[1].strip().split(" ")[0]: line.split("|")[2]
        for line in section.splitlines()
        if line.startswith("| ") and not line.startswith("| System")
    }

    assert set(rows) == {"Observability", "Code", "Tickets", "Chat"}
    bitbucket = set(re.findall(r"read:[a-z]+:bitbucket", rows["Code"]))
    assert bitbucket == set(re.findall(r"read:[a-z]+:bitbucket", standup))
    slack = set(re.findall(r"`([a-z]+:write)`", rows["Chat"]))
    assert slack == {"chat:write", "im:write"}
    assert slack <= set(re.findall(r"[a-z]+:write", daemon))
    for system, chosen in rows.items():
        assert not re.search(
            r"`[^`]*(write|admin|manage|delete)[^`]*`",
            chosen.replace("`chat:write`", "").replace("`im:write`", ""),
        ), system
    assert "keychain" in section
