# SPDX-License-Identifier: Apache-2.0
"""The leak check catches real-looking data and lets reserved values through (ADR-0015).

The synthetic leaks are assembled at run time, so this file never contains one.
"""

import time
from collections.abc import Callable
from pathlib import Path

import pytest

from tools.leak_check import (
    DenylistError,
    added_lines,
    check_identity,
    diff_files,
    find_config_dir,
    load_allowlist,
    load_denylist,
    main,
    scan_text,
)

ACCOUNT_ID = "2109" + "87654321"
DASHED_ACCOUNT_ID = "-".join(["2109", "8765", "4321"])
PRIVATE_IP = ".".join(["10", "20", "30", "40"])
CHAT_ID = "C0" + "1ABCD2EFG"
TICKET = "OPS" + "-1234"
HOSTNAME = "db01" + ".corp"
CONSUL_HOST = "db.service" + ".consul"
HOME_HOST = "nas" + ".home" + ".arpa"
RDS_ENDPOINT = "orders-db.abc123xyz.us-east-1" + ".rds" + ".amazonaws.com"
EMAIL = "jane.doe" + "@" + "mail-provider.com"
NO_CONFIG = "no-config"


def scan(text: str) -> list[str]:
    return [finding.rule for finding in scan_text(text, "notes.md", allowlist={}, denylist=[])]


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        (f"arn:aws:iam::{ACCOUNT_ID}:role/reader", "account-id"),
        (f"the console shows {DASHED_ACCOUNT_ID}", "account-id"),
        (f"role_{ACCOUNT_ID}", "account-id"),
        (f"ssh admin@{PRIVATE_IP}", "ip-address"),
        (f"posted in <#{CHAT_ID}>", "chat-id"),
        (f"see {TICKET} for details", "ticket-key"),
        (f"connect to {HOSTNAME}:5432", "hostname"),
        (f"resolve {CONSUL_HOST}", "hostname"),
        (f"open http://{HOME_HOST}/", "hostname"),
        (f"host: {RDS_ENDPOINT}", "cloud-endpoint"),
        (f"ask {EMAIL}", "e-mail"),
    ],
)
def test_generic_patterns_are_caught(text: str, rule: str) -> None:
    assert scan(text) == [rule]


@pytest.mark.parametrize(
    "text",
    [
        "arn:aws:iam::123456789012:role/reader and 1234-5678-9012",
        "the RFC 5737 hosts 192.0.2.10, 198.51.100.7 and 203.0.113.250",
        "127.0.0.1, 0.0.0.0 and the metadata service at 169.254.169.254",
        "write to someone@example.com or ID+login@users.noreply.github.com",
        "Signed-off-by: dependabot[bot] <support@github.com>",
        "git@github.com:owner/repo.git",
        "db.example.internal, host.docker.internal, kubernetes.default.svc.cluster.local",
        "orders-db.example.us-east-1.rds.amazonaws.com and s3.amazonaws.com",
        "EXAMPLE-123, ADR-0015, FR-002, SC-001, UTF-8 and SHA-256",
        "AES-256, RSA-2048, SHA3-256, X86-64, GPT-4, TLS-13 and Q4-2026",
        "https://www.apache.org/licenses/LICENSE-2.0 and HTTP-1.1",
        "CHECKSUM1 and DEPLOY2024",
        "CLAUDE.local.md and settings.local.json",
        "sha256:4f2a123456789012345b7c",
        "Python 3.13.3, uv 0.13.7 and v1.7.12.25",
        "#alerts-example in example-prod",
    ],
)
def test_reserved_and_harmless_values_pass(text: str) -> None:
    assert scan(text) == []


def test_a_long_dotted_line_is_scanned_quickly() -> None:
    line = "a." * 16_000 + "b"
    start = time.perf_counter()

    scan(line)

    assert time.perf_counter() - start < 2


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


def test_diff_files_lists_added_changed_and_binary_files_but_not_deleted_ones() -> None:
    diff = (
        "diff --git a/notes.md b/notes.md\n"
        "+++ b/notes.md\n"
        "@@ -1 +1 @@\n"
        "+text\n"
        "diff --git a/empty.txt b/empty.txt\n"
        "new file mode 100644\n"
        "diff --git a/data.csv b/data.csv\n"
        "Binary files /dev/null and b/data.csv differ\n"
        "diff --git a/old.txt b/old.txt\n"
        "deleted file mode 100644\n"
    )

    assert diff_files(diff) == [("notes.md", False), ("empty.txt", False), ("data.csv", True)]


def test_files_mode_reports_each_finding_with_its_location(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    note = tmp_path / "notes.md"
    note.write_text(f"line one\nhost {HOSTNAME}\n", encoding="utf-8")
    clean = tmp_path / "clean.md"
    clean.write_text("nothing to see\n", encoding="utf-8")
    blob = tmp_path / "image.png"
    blob.write_bytes(b"\x89PNG\x00" + PRIVATE_IP.encode())

    assert main(["files", str(clean), str(blob)]) == 0
    assert main(["files", str(note)]) == 1
    assert f"{note}:2: hostname: {HOSTNAME}" in capsys.readouterr().out


def test_files_mode_checks_file_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    note = tmp_path / f"notes-{TICKET}.md"
    note.write_text("nothing to see\n", encoding="utf-8")

    assert main(["files", str(note)]) == 1
    assert "(file name): ticket-key" in capsys.readouterr().out


def test_ci_output_is_always_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    note = tmp_path / "notes.md"
    note.write_text(f"host {HOSTNAME}\n", encoding="utf-8")

    assert main(["files", str(note)]) == 1
    assert HOSTNAME not in capsys.readouterr().out


def test_redacted_output_hides_the_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    note = tmp_path / "notes.md"
    note.write_text(f"host {HOSTNAME}\n", encoding="utf-8")

    assert main(["--redact", "files", str(note)]) == 1
    output = capsys.readouterr().out
    assert "hostname" in output
    assert HOSTNAME not in output


def test_message_mode_checks_the_message_but_not_comments_or_the_diff_below_scissors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    leaky = tmp_path / "LEAKY_MSG"
    leaky.write_text(f"fix: handle {TICKET}\n", encoding="utf-8")
    verbose = tmp_path / "VERBOSE_MSG"
    verbose.write_text(
        "fix: remove an address\n"
        f"# On branch {TICKET}\n"
        "# ------------------------ >8 ------------------------\n"
        f"-host {PRIVATE_IP}\n",
        encoding="utf-8",
    )

    assert main(["message", str(leaky)]) == 1
    assert main(["message", str(verbose)]) == 0


def test_identity_mode_names_the_fix_and_never_suggests_the_allowlist(
    git: Callable[..., str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git("config", "user.email", EMAIL)

    assert main(["identity"]) == 1
    hint = capsys.readouterr().err
    assert "git config user.email" in hint
    assert "leak_allowlist" not in hint


def test_a_clone_can_require_the_private_denylist(
    git: Callable[..., str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    clean = tmp_path / "clean.md"
    clean.write_text("nothing to see\n", encoding="utf-8")

    assert main(["files", str(clean)]) == 0
    git("config", "opscout.requireDenylist", "true")
    assert main(["files", str(clean)]) == 1


def test_commits_mode_checks_messages_addresses_names_and_contents(
    git: Callable[..., str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    repo = Path.cwd()
    (repo / "notes.md").write_text(f"host {HOSTNAME}\n", encoding="utf-8")
    git("add", ".")
    git("-c", f"user.email={EMAIL}", "commit", "-q", "-m", f"docs: mention {TICKET}")

    assert main(["commits", "HEAD"]) == 1
    output = capsys.readouterr().out
    assert "hostname" in output
    assert "ticket-key" in output
    assert "commit-e-mail" in output


def test_commits_mode_checks_renamed_names_and_files_git_treats_as_binary(
    git: Callable[..., str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    repo = Path.cwd()
    (repo / "notes.md").write_text("nothing to see\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "docs: add notes")
    base = git("rev-parse", "HEAD").strip()
    git("mv", "notes.md", f"notes-{TICKET}.md")
    (repo / ".gitattributes").write_text("*.csv -diff\n", encoding="utf-8")
    (repo / "data.csv").write_text(f"host,{HOSTNAME}\n", encoding="utf-8")
    (repo / "image.png").write_bytes(b"\x89PNG\x00" + PRIVATE_IP.encode())
    git("add", ".")
    git("commit", "-q", "-m", "docs: rename the notes")

    assert main(["commits", base, "HEAD"]) == 1
    output = capsys.readouterr().out
    assert "(file name): ticket-key" in output
    assert "data.csv:1: hostname" in output
    assert "ip-address" not in output


def test_commits_mode_ranges(
    git: Callable[..., str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    git("commit", "-q", "--allow-empty", "-m", "chore: start")
    first = git("rev-parse", "HEAD").strip()
    git("commit", "-q", "--allow-empty", "-m", f"fix: handle {TICKET}")

    assert main(["commits", first]) == 0
    assert main(["commits", first, "HEAD"]) == 1
    assert main(["commits", "0" * 40, "HEAD"]) == 1


def test_pushed_mode_reads_the_range_pre_commit_passes(
    git: Callable[..., str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    git("commit", "-q", "--allow-empty", "-m", "chore: start")
    first = git("rev-parse", "HEAD").strip()
    git("commit", "-q", "--allow-empty", "-m", f"fix: handle {TICKET}")
    second = git("rev-parse", "HEAD").strip()

    monkeypatch.setenv("PRE_COMMIT_FROM_REF", first)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", first)
    assert main(["pushed"]) == 0
    monkeypatch.setenv("PRE_COMMIT_TO_REF", second)
    assert main(["pushed"]) == 1
