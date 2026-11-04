# SPDX-License-Identifier: Apache-2.0
"""The leak check catches real-looking data and lets reserved values through (ADR-0015).

The synthetic leaks are assembled at run time, so this file never contains one.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from tools.leak_check import (
    DenylistError,
    added_lines,
    check_identity,
    find_config_dir,
    load_allowlist,
    load_denylist,
    main,
    scan_text,
)

ACCOUNT_ID = "2109" + "87654321"
PRIVATE_IP = ".".join(["10", "20", "30", "40"])
CHAT_ID = "C0" + "1ABCD2EFG"
TICKET = "OPS" + "-1234"
HOSTNAME = "db01" + ".corp"
EMAIL = "jane.doe" + "@" + "mail-provider.com"


@pytest.fixture(autouse=True)
def outside_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI redacts every value; these tests run as on a laptop unless they say otherwise."""
    monkeypatch.delenv("CI", raising=False)


def scan(text: str) -> list[str]:
    return [finding.rule for finding in scan_text(text, "notes.md", allowlist={}, denylist=[])]


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        (f"arn:aws:iam::{ACCOUNT_ID}:role/reader", "account-id"),
        (f"ssh admin@{PRIVATE_IP}", "ip-address"),
        (f"posted in <#{CHAT_ID}>", "chat-id"),
        (f"see {TICKET} for details", "ticket-key"),
        (f"connect to {HOSTNAME}:5432", "hostname"),
        (f"ask {EMAIL}", "e-mail"),
    ],
)
def test_generic_patterns_are_caught(text: str, rule: str) -> None:
    assert scan(text) == [rule]


@pytest.mark.parametrize(
    "text",
    [
        "arn:aws:iam::123456789012:role/reader",
        "the RFC 5737 hosts 192.0.2.10, 198.51.100.7 and 203.0.113.250",
        "127.0.0.1, 0.0.0.0 and the metadata service at 169.254.169.254",
        "write to someone@example.com or ID+login@users.noreply.github.com",
        "git@github.com:owner/repo.git",
        "db.example.internal",
        "EXAMPLE-123, ADR-0015, FR-002, SC-001, UTF-8 and SHA-256",
        "https://www.apache.org/licenses/LICENSE-2.0 and HTTP-1.1",
        "CLAUDE.local.md and settings.local.json",
        "sha256:4f2a123456789012345b7c",
        "Python 3.13.3, uv 0.13.7 and v1.7.12.25",
        "#alerts-example in example-prod",
    ],
)
def test_reserved_and_harmless_values_pass(text: str) -> None:
    assert scan(text) == []


def test_an_allowlisted_value_passes(tmp_path: Path) -> None:
    allowlist_file = tmp_path / "allow.toml"
    allowlist_file.write_text(
        f'[[allow]]\nvalue = "{PRIVATE_IP}"\nreason = "A synthetic value in a test."\n',
        encoding="utf-8",
    )
    allowlist = load_allowlist(allowlist_file)

    assert scan_text(f"ping {PRIVATE_IP}", "notes.md", allowlist=allowlist, denylist=[]) == []


def test_an_allowlist_entry_needs_a_reason(tmp_path: Path) -> None:
    allowlist_file = tmp_path / "allow.toml"
    allowlist_file.write_text(f'[[allow]]\nvalue = "{PRIVATE_IP}"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="reason"):
        load_allowlist(allowlist_file)


def test_private_terms_are_caught_even_when_allowlisted(tmp_path: Path) -> None:
    (tmp_path / "leak-denylist.txt").write_text(
        "# Private terms, one regular expression per line.\n\nacme[- ]?corp\n", encoding="utf-8"
    )
    denylist = load_denylist(tmp_path)
    assert denylist is not None

    findings = scan_text(
        "deploy for ACME-Corp", "notes.md", allowlist={"ACME-Corp": "no"}, denylist=denylist
    )

    assert [(finding.rule, finding.value) for finding in findings] == [
        ("private-term", "ACME-Corp")
    ]


def test_a_missing_denylist_is_not_an_error(tmp_path: Path) -> None:
    assert load_denylist(tmp_path) is None


def test_an_invalid_denylist_entry_names_its_line(tmp_path: Path) -> None:
    (tmp_path / "leak-denylist.txt").write_text("valid\n(unclosed\n", encoding="utf-8")

    with pytest.raises(DenylistError, match="line 2"):
        load_denylist(tmp_path)


def test_the_config_directory_is_resolved_as_adr_0014_says(tmp_path: Path) -> None:
    home = tmp_path / "home"

    assert find_config_dir({"OPSCOUT_CONFIG": str(tmp_path)}, home) == tmp_path
    assert find_config_dir({}, home) == home / ".config" / "opscout"


@pytest.mark.parametrize(
    "email",
    [
        "12345+someone@users.noreply.github.com",
        "someone@users.noreply.github.com",
        "49699333+dependabot[bot]@users.noreply.github.com",
        "noreply@github.com",
    ],
)
def test_github_noreply_addresses_are_accepted(email: str) -> None:
    assert check_identity(email, "author") is None


def test_any_other_commit_address_is_rejected() -> None:
    finding = check_identity(EMAIL, "author")

    assert finding is not None
    assert finding.rule == "commit-e-mail"


def test_added_lines_carry_their_path_and_line_number() -> None:
    diff = (
        "diff --git a/notes.md b/notes.md\n"
        "--- a/notes.md\n"
        "+++ b/notes.md\n"
        "@@ -3,0 +4,2 @@\n"
        "+first\n"
        "++++ an added line that starts with plus signs\n"
        "diff --git a/old.txt b/old.txt\n"
        "deleted file mode 100644\n"
        "--- a/old.txt\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-gone\n"
    )

    assert list(added_lines(diff)) == [
        ("notes.md", 4, "first"),
        ("notes.md", 5, "+++ an added line that starts with plus signs"),
    ]


def test_files_mode_reports_each_finding_with_its_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / "no-config"))
    note = tmp_path / "notes.md"
    note.write_text(f"line one\nhost {HOSTNAME}\n", encoding="utf-8")
    clean = tmp_path / "clean.md"
    clean.write_text("nothing to see\n", encoding="utf-8")
    blob = tmp_path / "image.png"
    blob.write_bytes(b"\x89PNG\x00" + PRIVATE_IP.encode())

    assert main(["files", str(clean), str(blob)]) == 0
    assert main(["files", str(note)]) == 1
    assert f"{note}:2: hostname: {HOSTNAME}" in capsys.readouterr().out


def test_ci_output_is_always_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / "no-config"))
    note = tmp_path / "notes.md"
    note.write_text(f"host {HOSTNAME}\n", encoding="utf-8")

    assert main(["files", str(note)]) == 1
    assert HOSTNAME not in capsys.readouterr().out


def test_redacted_output_hides_the_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / "no-config"))
    note = tmp_path / "notes.md"
    note.write_text(f"host {HOSTNAME}\n", encoding="utf-8")

    assert main(["--redact", "files", str(note)]) == 1
    output = capsys.readouterr().out
    assert "hostname" in output
    assert HOSTNAME not in output


def test_message_mode_checks_the_commit_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / "no-config"))
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text(f"fix: handle {TICKET}\n", encoding="utf-8")

    assert main(["message", str(message)]) == 1


def test_commits_mode_checks_messages_addresses_and_added_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    git = shutil.which("git")
    assert git is not None
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "notes.md").write_text(f"host {HOSTNAME}\n", encoding="utf-8")
    for arguments in (
        ["init", "-q"],
        ["add", "notes.md"],
        [
            "-c",
            "user.name=Someone",
            "-c",
            f"user.email={EMAIL}",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            f"docs: mention {TICKET}",
        ],
    ):
        subprocess.run([git, *arguments], cwd=repo, check=True)  # noqa: S603  # fixed program
    monkeypatch.chdir(repo)
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / "no-config"))

    assert main(["commits", "HEAD"]) == 1
    output = capsys.readouterr().out
    assert "hostname" in output
    assert "ticket-key" in output
    assert "commit-e-mail" in output
