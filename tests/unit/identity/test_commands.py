# SPDX-License-Identifier: Apache-2.0
"""`opscout identity check | export` and the pre-commit hook (spec 010, FR-001, FR-016)."""

import json
import socket
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
import yaml

from opscout.adapters.identity_files import load_records, reference_files
from opscout.entrypoints.cli import main

REPO_ROOT = Path(__file__).resolve().parents[3]


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 010."""
    return pytest.mark.spec("010", requirement)


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the command opened a network connection")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@spec("FR-016")
def test_check_without_a_directory_proves_the_packaged_reference(
    capsys: pytest.CaptureFixture[str], offline: None
) -> None:
    records = load_records()

    assert main(["identity", "check"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"Catalog: AWS service reference, fetched {records.catalog.fetched} ")
    assert f"ViewOnlyAccess {records.view_only.version}" in out
    assert "Read-only identity: secret reads " in out
    assert "Host documents: 7/7 match the reference" in out
    assert out.endswith("Pass.\n")


@spec("FR-016")
def test_export_then_check_is_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], offline: None
) -> None:
    target = tmp_path / "opscout-identity"

    assert main(["identity", "export", str(target)]) == 0
    out = capsys.readouterr().out
    assert "aws/guardrail.json" in out
    assert "123456789012" in out
    assert "example-prod" in out
    assert not (target / "catalog.json").exists()
    assert not (target / "managed").exists()
    assert main(["identity", "check", str(target)]) == 0
    assert capsys.readouterr().out.endswith("Pass.\n")


@spec("FR-016")
def test_findings_are_printed_one_per_line_and_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["identity", "export", str(tmp_path)])
    capsys.readouterr()
    guardrail = tmp_path / "aws" / "guardrail.json"
    document = json.loads(guardrail.read_text(encoding="utf-8"))
    document["Statement"] = [s for s in document["Statement"] if s["Sid"] != "DenySecretValues"]
    guardrail.write_text(json.dumps(document), encoding="utf-8")
    (tmp_path / "aws" / "extra.json").write_text("{}", encoding="utf-8")

    assert main(["identity", "check", str(tmp_path)]) == 1
    lines = capsys.readouterr().out.splitlines()
    assert "layout: aws/extra.json is not part of the identity" in lines
    assert any(line.startswith("secret-allowed: ssm:GetParameter ") for line in lines)
    assert lines[-1].startswith("Fail: ")
    assert lines[-1].endswith(" findings.")


@spec("FR-016")
def test_a_missing_directory_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["identity", "check", str(tmp_path / "absent")]) == 2
    assert "no such directory" in capsys.readouterr().err


@spec("FR-016")
def test_an_unparseable_file_exits_2_naming_file_and_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "aws").mkdir()
    (tmp_path / "aws" / "guardrail.json").write_text('{\n "Version":\n}', encoding="utf-8")

    assert main(["identity", "check", str(tmp_path)]) == 2
    assert "aws/guardrail.json:3:" in capsys.readouterr().err


@spec("FR-016")
def test_export_never_overwrites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "aws").mkdir()
    existing = tmp_path / "aws" / "guardrail.json"
    existing.write_text("mine", encoding="utf-8")

    assert main(["identity", "export", str(tmp_path)]) == 2
    assert "nothing written" in capsys.readouterr().err
    assert existing.read_text(encoding="utf-8") == "mine"
    assert not (tmp_path / "ssm").exists()


@spec("FR-016")
def test_the_pre_commit_hook_runs_the_check() -> None:
    hooks = yaml.safe_load((REPO_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))
    by_id = {hook["id"]: hook for hook in hooks}

    assert "opscout-config-validate" in by_id
    hook = by_id["opscout-identity-check"]
    assert hook["entry"] == "opscout identity check"
    assert hook["pass_filenames"] is False
    assert hook["language"] == "python"


@spec("FR-001")
def test_every_reference_file_ships_in_the_package() -> None:
    root = files("opscout").joinpath("data", "identity")

    for name in ("catalog.json", "capabilities.json", "guardrail-actions.json"):
        assert root.joinpath(name).is_file()
    for name in ("ViewOnlyAccess.json", "ReadOnlyAccess.json"):
        assert root.joinpath("managed", name).is_file()
    paths = [path for path, _ in reference_files()]
    assert len(paths) == 18
    for path in paths:
        assert root.joinpath(*path.split("/")).is_file()
