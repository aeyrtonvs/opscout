# SPDX-License-Identifier: Apache-2.0
"""Hosts run only allow-listed commands (spec 010, FR-002, FR-003, FR-007-FR-009, FR-013)."""

import copy
import re
from typing import Any

import pytest

from opscout.adapters.identity_files import load_records
from opscout.core.identity import (
    Analysis,
    Records,
    Report,
    Tree,
    proves_allowed,
    proves_denied,
    with_allow_all,
)
from opscout.services.identity import hosts_identity, prove, readonly_identity

DOCUMENTS = {
    "Uptime",
    "Memory",
    "Disk",
    "TopProcesses",
    "ServiceState",
    "ServiceLog",
    "ListeningPorts",
}
ACCOUNT = "123456789012"
INSTANCE = f"arn:aws:ec2:us-east-1:{ACCOUNT}:instance/i-0123456789abcdef0"
MANAGED = f"arn:aws:ssm:us-east-1:{ACCOUNT}:managed-instance/mi-0123456789abcdef0"
INJECTIONS = [
    ";",
    "$(id)",
    "`id`",
    "a|b",
    "a&b",
    "a>b",
    "a\nb",
    "..",
    "/etc/passwd",
    "a b",
    '"',
    "'",
    "nginx; rm -rf /",
    "-o",
    "",
    "a" * 65,
    "nginx\n",  # a Java $ would accept it; SSM Agent's Go regexp refuses it (research R5)
]
FORBIDDEN = re.compile(
    r"\{\{|\benv\b|\bprintenv\b|\bset\b|\bcat (?!/proc/loadavg)|systemctl status|args"
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


@pytest.fixture(scope="module")
def records() -> Records:
    return load_records()


def _documents(records: Records) -> dict[str, dict[str, Any]]:
    return {
        path.removeprefix("ssm/opscout-ReadOnly-").removesuffix(".yaml"): document[0]
        for path, document in records.reference.files.items()
        if path.startswith("ssm/")
    }


def _arn(name: str, account: str = ACCOUNT) -> str:
    return f"arn:aws:ssm:us-east-1:{account}:document/{name}"


def _messages(report: Report, kind: str) -> str:
    return "\n".join(f.message for f in report.findings if f.kind == kind)


@spec("FR-007")
def test_seven_linux_documents_cover_the_command_groups(records: Records) -> None:
    documents = _documents(records)

    assert set(documents) == DOCUMENTS
    for document in documents.values():
        assert document["schemaVersion"] == "2.2"
        (step,) = document["mainSteps"]
        assert step["action"] == "aws:runShellScript"
        assert step["precondition"] == {"StringEquals": ["platformType", "Linux"]}


@spec("FR-008")
def test_every_parameter_refuses_the_injection_corpus(records: Records) -> None:
    parameters = [
        parameter
        for document in _documents(records).values()
        for parameter in document.get("parameters", {}).values()
    ]
    assert parameters
    for parameter in parameters:
        assert parameter["interpolationType"] == "ENV_VAR"
        for value in INJECTIONS:
            if "allowedValues" in parameter:
                assert value not in parameter["allowedValues"]
            else:
                assert not re.fullmatch(parameter["allowedPattern"], value), value
    service = _documents(records)["ServiceState"]["parameters"]["ServiceName"]["allowedPattern"]
    for name in ("nginx", "sshd.service", "getty@tty1", "systemd-journald"):
        assert re.fullmatch(service, name), name


@spec("FR-008")
def test_no_command_prints_the_environment_or_reads_a_given_file(records: Records) -> None:
    for name, document in _documents(records).items():
        for command in document["mainSteps"][0]["inputs"]["runCommand"]:
            assert not FORBIDDEN.search(command), (name, command)
            for variable in re.findall(r"\$\{?(\w+)", command):
                assert variable.startswith("SSM_"), (name, command)
                assert f'"${variable}"' in command, (name, command)


@spec("FR-009")
def test_the_host_identity_sends_every_catalog_document_on_instances(records: Records) -> None:
    identity = hosts_identity(records.reference, records)
    assert identity is not None

    for name in DOCUMENTS:
        for target in (INSTANCE, MANAGED):
            assert proves_allowed(
                identity, "ssm:SendCommand", _arn(f"opscout-ReadOnly-{name}"), target
            ) == (True, None)


@spec("FR-003")
@pytest.mark.parametrize(
    ("action", "resource"),
    [
        ("ssm:SendCommand", "arn:aws:ssm:us-east-1::document/AWS-RunShellScript"),
        ("ssm:SendCommand", "arn:aws:ssm:us-east-1::document/AWS-RunPowerShellScript"),
        ("ssm:SendCommand", _arn("example-other")),
        ("ssm:SendCommand", _arn("opscout-ReadOnly-Unlisted")),
        ("ssm:StartSession", INSTANCE),
        ("ssm:StartAutomationExecution", "*"),
        ("ec2-instance-connect:SendSSHPublicKey", INSTANCE),
    ],
)
def test_the_host_identity_is_denied_shells_sessions_and_other_documents(
    records: Records, action: str, resource: str
) -> None:
    identity = hosts_identity(records.reference, records)
    assert identity is not None

    assert proves_denied(with_allow_all(identity), action, resource, INSTANCE)[0]


@spec("FR-009")
def test_the_read_only_identity_cannot_send_any_command(records: Records) -> None:
    robust = Analysis(
        with_allow_all(readonly_identity(records.reference, records)), records.catalog
    )

    assert robust.denied_everywhere("ssm:sendcommand") is not None


@spec("FR-002")
def test_send_command_is_the_host_identitys_only_write(records: Records) -> None:
    identity = hosts_identity(records.reference, records)
    assert identity is not None
    analysis = Analysis(with_allow_all(identity), records.catalog)

    allowed = [
        key
        for key in records.catalog
        if records.catalog.is_write(key) and analysis.denied_everywhere(key) is None
    ]
    assert allowed == ["ssm:sendcommand"]
    assert "1 exception (ssm:SendCommand on 7 documents)" in "\n".join(
        prove(records.reference, records).summary
    )


@spec("FR-013")
def test_a_document_that_prints_the_environment_is_named(records: Records) -> None:
    files = copy.deepcopy(dict(records.reference.files))
    files["ssm/opscout-ReadOnly-Disk.yaml"][0]["mainSteps"][0]["inputs"]["runCommand"].append("env")

    report = prove(Tree(files), records)

    assert _messages(report, "host-document") == (
        "ssm/opscout-ReadOnly-Disk.yaml differs from the reference at "
        "mainSteps[0].inputs.runCommand[2]"
    )


@spec("FR-013")
def test_a_loosened_pattern_is_named(records: Records) -> None:
    files = copy.deepcopy(dict(records.reference.files))
    files["ssm/opscout-ReadOnly-ServiceLog.yaml"][0]["parameters"]["ServiceName"][
        "allowedPattern"
    ] = ".*"

    report = prove(Tree(files), records)

    assert "ssm/opscout-ReadOnly-ServiceLog.yaml differs from the reference at " in _messages(
        report, "host-pattern"
    )


@spec("FR-013")
def test_a_command_reading_a_given_file_is_named(records: Records) -> None:
    files = copy.deepcopy(dict(records.reference.files))
    step = files["ssm/opscout-ReadOnly-ServiceLog.yaml"][0]["mainSteps"][0]
    step["inputs"]["runCommand"] = ['cat "$SSM_ServiceName"']

    report = prove(Tree(files), records)

    assert "runCommand[0]" in _messages(report, "host-document")


@spec("FR-003")
def test_a_wider_send_command_is_too_wide(records: Records) -> None:
    files = copy.deepcopy(dict(records.reference.files))
    for path in ("aws/hosts/capability.json", "aws/hosts/boundary.json"):
        files[path]["Statement"][0]["Resource"].append(
            f"arn:aws:ssm:*:{ACCOUNT}:document/AWS-RunShellScript"
        )
        files[path]["Statement"][0]["Resource"].append("arn:aws:ssm:*::document/*")
    del files["aws/guardrail.json"]["Statement"][-1]

    report = prove(Tree(files), records)

    assert "AWS-RunShellScript" in _messages(report, "exception-too-wide")
