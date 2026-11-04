# SPDX-License-Identifier: Apache-2.0
"""The leak check catches real-looking data and lets reserved values through (spec 001).

The synthetic leaks are assembled at run time, so this file never contains one (FR-029).
Every test is tied to the requirements of ``specs/001-leak-guard/spec.md`` it proves, and a
traceability test fails when a requirement has none (FR-030).
"""

import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

import tools.leak_check
from tools._git import git as run_git
from tools.leak_check import (
    ALLOWLIST_FILE,
    DEFAULT_HINT,
    HINTS,
    RULES,
    DenylistError,
    _scan_commits,
    added_lines,
    check_identity,
    find_config_dir,
    load_allowlist,
    load_denylist,
    main,
    scan_text,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_FILE = REPO_ROOT / "specs" / "001-leak-guard" / "spec.md"

ACCOUNT_ID = "2109" + "87654321"
DASHED_ACCOUNT_ID = "-".join(["2109", "8765", "4321"])
PRIVATE_IP = ".".join(["10", "20", "30", "40"])
CHAT_ID = "C0" + "1ABCD2EFG"
TICKET = "OPS" + "-1234"
HOSTNAME = "db01" + ".corp"
CONSUL_HOST = "db.service" + ".consul"
HOME_HOST = "nas" + ".home" + ".arpa"
INTERNAL_HOST = "build01" + ".internal"
LOCAL_HOST = "printer" + ".local"
LAN_HOST = "nas" + ".lan"
INTRANET_HOST = "wiki" + ".intranet"
RDS_ENDPOINT = "orders-db.abc123xyz.us-east-1" + ".rds" + ".amazonaws.com"
LEGACY_S3_ENDPOINT = "logs-bucket" + ".s3-us-west-2" + ".amazonaws.com"
S3_WEBSITE_ENDPOINT = "www-site" + ".s3-website-us-east-1" + ".amazonaws.com"
ELB_ENDPOINT = "web-alb-42.us-east-1" + ".elb" + ".amazonaws.com"
API_ENDPOINT = "a1b2c3d4e5" + ".execute-api" + ".us-east-1" + ".amazonaws.com"
EMAIL = "jane.doe" + "@" + "mail-provider.com"
PRIVATE_TERM = "acme" + "-corp"
DENYLIST = "# Private terms, one regular expression per line.\n\nacme[- ]?corp\n"
NO_CONFIG = "no-config"

# The requirement that proves each layer-1 rule (FR-001 to FR-007).
RULE_REQUIREMENT = {
    "account-id": "FR-001",
    "ip-address": "FR-002",
    "chat-id": "FR-003",
    "ticket-key": "FR-004",
    "hostname": "FR-005",
    "cloud-endpoint": "FR-006",
    "e-mail": "FR-007",
}


def case(text: str, rule: str) -> pytest.ParameterSet:
    """A layer-1 case, tied to the requirement of its rule and to FR-028."""
    return pytest.param(
        text,
        rule,
        marks=[pytest.mark.spec("001", RULE_REQUIREMENT[rule]), pytest.mark.spec("001", "FR-028")],
    )


def scan(text: str) -> list[str]:
    return [finding.rule for finding in scan_text(text, "notes.md", allowlist={}, denylist=[])]


def write_denylist(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "leak-denylist.txt").write_text(DENYLIST, encoding="utf-8")
    return directory


CAUGHT = [
    case(f"arn:aws:iam::{ACCOUNT_ID}:role/reader", "account-id"),
    case(f"the console shows {DASHED_ACCOUNT_ID}", "account-id"),
    case(f"role_{ACCOUNT_ID}", "account-id"),
    case(f"ssh admin@{PRIVATE_IP}", "ip-address"),
    case(f"posted in <#{CHAT_ID}>", "chat-id"),
    case(f"see {TICKET} for details", "ticket-key"),
    case(f"connect to {HOSTNAME}:5432", "hostname"),
    case(f"resolve {CONSUL_HOST}", "hostname"),
    case(f"open http://{HOME_HOST}/", "hostname"),
    case(f"ssh {INTERNAL_HOST}", "hostname"),
    case(f"print to {LOCAL_HOST}", "hostname"),
    case(f"mount {LAN_HOST}:/share", "hostname"),
    case(f"read https://{INTRANET_HOST}/page", "hostname"),
    case(f"host: {RDS_ENDPOINT}", "cloud-endpoint"),
    case(f"bucket: {LEGACY_S3_ENDPOINT}", "cloud-endpoint"),
    case(f"site: {S3_WEBSITE_ENDPOINT}", "cloud-endpoint"),
    case(f"balancer: {ELB_ENDPOINT}", "cloud-endpoint"),
    case(f"api: https://{API_ENDPOINT}/prod", "cloud-endpoint"),
    case(f"ask {EMAIL}", "e-mail"),
]

# Each harmless case names the rule whose shape it has.
HARMLESS = [
    case("arn:aws:iam::123456789012:role/reader and 1234-5678-9012", "account-id"),
    case("sha256:4f2a123456789012345b7c", "account-id"),
    case("the RFC 5737 hosts 192.0.2.10, 198.51.100.7 and 203.0.113.250", "ip-address"),
    case("127.0.0.1, 0.0.0.0 and the metadata service at 169.254.169.254", "ip-address"),
    case("Python 3.13.3, uv 0.13.7 and v1.7.12.25", "ip-address"),
    case("a dotted value such as 999.1.2.3 is not an address", "ip-address"),
    case("CHECKSUM1 and DEPLOY2024", "chat-id"),
    case("#alerts-example in example-prod", "chat-id"),
    case("EXAMPLE-123, ADR-0015, FR-002, SC-001, UTF-8 and SHA-256", "ticket-key"),
    case("AES-256, RSA-2048, SHA3-256, X86-64, GPT-4, TLS-13 and Q4-2026", "ticket-key"),
    case("https://www.apache.org/licenses/LICENSE-2.0 and HTTP-1.1", "ticket-key"),
    case(
        "db.example.internal, host.docker.internal, kubernetes.default.svc.cluster.local",
        "hostname",
    ),
    case("CLAUDE.local.md and settings.local.json", "hostname"),
    case("orders-db.example.us-east-1.rds.amazonaws.com and s3.amazonaws.com", "cloud-endpoint"),
    case("write to someone@example.com or ID+login@users.noreply.github.com", "e-mail"),
    case("Signed-off-by: dependabot[bot] <support@github.com>", "e-mail"),
    case("git@github.com:owner/repo.git", "e-mail"),
]


@pytest.mark.parametrize(("text", "rule"), CAUGHT)
def test_generic_patterns_are_caught(text: str, rule: str) -> None:
    assert scan(text) == [rule]


@pytest.mark.parametrize(("text", "rule"), HARMLESS)
def test_reserved_and_harmless_values_pass(text: str, rule: str) -> None:
    assert scan(text) == []


@pytest.mark.spec("001", "FR-028")
def test_every_rule_is_proven_both_ways() -> None:
    rules = {rule.name for rule in RULES}

    assert {param.values[1] for param in CAUGHT} == rules
    assert {param.values[1] for param in HARMLESS} == rules
    assert set(RULE_REQUIREMENT) == rules


@pytest.mark.spec("001", "FR-029")
def test_this_file_holds_no_leak() -> None:
    text = Path(__file__).read_text(encoding="utf-8")

    assert scan_text(text, "test", allowlist=load_allowlist(ALLOWLIST_FILE), denylist=[]) == []


@pytest.mark.spec("001", "FR-031")
def test_a_long_dotted_line_is_scanned_quickly() -> None:
    line = "a." * 16_000 + "b"
    start = time.perf_counter()

    scan(line)

    assert time.perf_counter() - start < 2


@pytest.mark.spec("001", "FR-031")
def test_a_typical_change_is_checked_in_under_a_second(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "leak-denylist.txt").write_text("# no terms\n", encoding="utf-8")
    paths = []
    for number in range(20):
        path = tmp_path / f"module_{number}.py"
        lines = [
            f"value_{line} = compute({line}, host='db.example.internal')  # see ADR-0015"
            for line in range(50)
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        paths.append(str(path))
    environment = {**os.environ, "OPSCOUT_CONFIG": str(config), "PYTHONPATH": str(REPO_ROOT)}
    start = time.perf_counter()

    completed = subprocess.run(  # noqa: S603  # the current interpreter, on files made here
        [sys.executable, "-m", "tools.leak_check", "files", *paths],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    elapsed = time.perf_counter() - start
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert elapsed < 1


@pytest.mark.spec("001", "FR-026")
def test_an_allowlisted_value_passes(tmp_path: Path) -> None:
    allowlist_file = tmp_path / "allow.toml"
    allowlist_file.write_text(
        f'[[allow]]\nvalue = "{PRIVATE_IP}"\nreason = "A synthetic value in a test."\n',
        encoding="utf-8",
    )
    allowlist = load_allowlist(allowlist_file)

    assert scan_text(f"ping {PRIVATE_IP}", "notes.md", allowlist=allowlist, denylist=[]) == []


@pytest.mark.spec("001", "FR-025")
def test_an_allowlist_entry_needs_a_reason(tmp_path: Path) -> None:
    allowlist_file = tmp_path / "allow.toml"
    allowlist_file.write_text(f'[[allow]]\nvalue = "{PRIVATE_IP}"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="entry 1 needs a reason"):
        load_allowlist(allowlist_file)


@pytest.mark.spec("001", "FR-025")
def test_an_allowlist_entry_needs_a_value(tmp_path: Path) -> None:
    allowlist_file = tmp_path / "allow.toml"
    allowlist_file.write_text(
        '[[allow]]\nvalue = "x"\nreason = "fine"\n\n[[allow]]\nreason = "no value"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="entry 2 needs a value"):
        load_allowlist(allowlist_file)


@pytest.mark.spec("001", "FR-027")
@pytest.mark.parametrize("value", sorted(load_allowlist(ALLOWLIST_FILE)))
def test_every_allowlist_entry_is_still_needed(value: str) -> None:
    assert scan(value), f"no rule matches {value!r} any more: remove it from the allow-list"


@pytest.mark.spec("001", "FR-008")
@pytest.mark.spec("001", "FR-009")
def test_private_terms_are_caught_even_when_allowlisted(tmp_path: Path) -> None:
    denylist = load_denylist(write_denylist(tmp_path))
    assert denylist is not None

    findings = scan_text(
        "deploy for ACME-Corp", "notes.md", allowlist={"ACME-Corp": "no"}, denylist=denylist
    )

    assert [(finding.rule, finding.value) for finding in findings] == [
        ("private-term", "ACME-Corp")
    ]


@pytest.mark.spec("001", "FR-009")
def test_private_terms_are_caught_in_file_names_and_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(write_denylist(tmp_path / "config")))
    named = tmp_path / f"{PRIVATE_TERM.upper()}-notes.md"
    named.write_text("nothing to see\n", encoding="utf-8")
    message = tmp_path / "MSG"
    message.write_text(f"fix: the {PRIVATE_TERM.title()} login\n", encoding="utf-8")

    assert main(["files", str(named)]) == 1
    assert "(file name): private-term" in capsys.readouterr().out
    assert main(["message", str(message)]) == 1
    assert "MSG:1: private-term" in capsys.readouterr().out


@pytest.mark.spec("001", "FR-010")
def test_a_missing_denylist_is_not_an_error(tmp_path: Path) -> None:
    assert load_denylist(tmp_path) is None


@pytest.mark.spec("001", "FR-010")
def test_a_missing_denylist_is_skipped_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    note = tmp_path / "notes.md"
    note.write_text(f"host {HOSTNAME}\n", encoding="utf-8")

    assert main(["files", str(note)]) == 1
    captured = capsys.readouterr()
    assert "layer 2 was skipped" in captured.err
    assert "hostname" in captured.out


@pytest.mark.spec("001", "FR-011")
def test_an_invalid_denylist_entry_names_its_line(tmp_path: Path) -> None:
    (tmp_path / "leak-denylist.txt").write_text("valid\n(unclosed\n", encoding="utf-8")

    with pytest.raises(DenylistError, match="line 2"):
        load_denylist(tmp_path)


@pytest.mark.spec("001", "FR-011")
def test_an_invalid_denylist_entry_stops_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "leak-denylist.txt").write_text("valid\n(unclosed\n", encoding="utf-8")
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path))
    note = tmp_path / "notes.md"
    note.write_text(f"host {HOSTNAME}\n", encoding="utf-8")

    with pytest.raises(SystemExit) as stopped:
        main(["files", str(note)])

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert "line 2" in captured.err
    assert captured.out == ""


@pytest.mark.spec("001", "FR-012")
def test_this_repository_never_holds_a_denylist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)
    tracked = run_git("ls-files", "-z").split("\0")

    assert not [name for name in tracked if Path(name).name == "leak-denylist.txt"]
    run_git("check-ignore", "-q", "--no-index", "leak-denylist.txt")


@pytest.mark.spec("001", "FR-008")
def test_the_config_directory_is_resolved_as_adr_0014_says(tmp_path: Path) -> None:
    home = tmp_path / "home"

    assert find_config_dir({"OPSCOUT_CONFIG": str(tmp_path)}, home) == tmp_path
    assert find_config_dir({}, home) == home / ".config" / "opscout"


@pytest.mark.spec("001", "FR-013")
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


@pytest.mark.spec("001", "FR-013")
def test_any_other_commit_address_is_rejected() -> None:
    finding = check_identity(EMAIL, "author")

    assert finding is not None
    assert finding.rule == "commit-e-mail"


@pytest.mark.spec("001", "FR-018")
@pytest.mark.spec("001", "FR-021")
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


@pytest.mark.spec("001", "FR-015")
@pytest.mark.spec("001", "FR-022")
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


@pytest.mark.spec("001", "FR-015")
def test_files_mode_checks_file_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    note = tmp_path / f"notes-{TICKET}.md"
    note.write_text("nothing to see\n", encoding="utf-8")

    assert main(["files", str(note)]) == 1
    assert "(file name): ticket-key" in capsys.readouterr().out


@pytest.mark.spec("001", "FR-023")
def test_layer_1_findings_share_one_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    note = tmp_path / "notes.md"
    note.write_text(f"host {HOSTNAME}\nsee {TICKET}\n", encoding="utf-8")

    assert main(["files", str(note)]) == 1
    assert capsys.readouterr().err.count(DEFAULT_HINT) == 1


@pytest.mark.spec("001", "FR-023")
def test_each_kind_of_finding_gets_its_own_hint(
    git: Callable[..., str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(write_denylist(tmp_path / "config")))
    git(
        "-c",
        f"user.email={EMAIL}",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        f"fix: handle {TICKET} for {PRIVATE_TERM}",
    )

    assert main(["commits", "HEAD"]) == 1
    hints = capsys.readouterr().err
    assert hints.count(DEFAULT_HINT) == 1
    assert hints.count(HINTS["commit-e-mail"]) == 1
    assert hints.count(HINTS["private-term"]) == 1


@pytest.mark.spec("001", "FR-024")
def test_ci_output_is_always_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    note = tmp_path / "notes.md"
    note.write_text(f"host {HOSTNAME}\n", encoding="utf-8")

    assert main(["files", str(note)]) == 1
    assert HOSTNAME not in capsys.readouterr().out


@pytest.mark.spec("001", "FR-024")
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


@pytest.mark.spec("001", "FR-024")
def test_redaction_also_hides_values_in_file_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    note = tmp_path / f"{TICKET}-{CHAT_ID}.md"
    note.write_text("nothing to see\n", encoding="utf-8")

    assert main(["files", str(note)]) == 1
    output = capsys.readouterr().out
    assert "ticket-key" in output
    assert "chat-id" in output
    assert TICKET not in output
    assert CHAT_ID not in output


@pytest.mark.spec("001", "FR-016")
def test_message_mode_checks_comment_lines_but_not_the_diff_below_scissors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    leaky = tmp_path / "LEAKY_MSG"
    leaky.write_text(f"fix: handle {TICKET}\n", encoding="utf-8")
    verbose = tmp_path / "VERBOSE_MSG"
    verbose.write_text(
        "fix: remove an address\n"
        "# On branch main\n"
        "# ------------------------ >8 ------------------------\n"
        f"-host {PRIVATE_IP}\n",
        encoding="utf-8",
    )
    kept_comment = tmp_path / "KEPT_MSG"
    kept_comment.write_text(f"docs: add context\n\n# Context: {TICKET}\n", encoding="utf-8")

    assert main(["message", str(leaky)]) == 1
    assert main(["message", str(verbose)]) == 0
    assert main(["message", str(kept_comment)]) == 1


@pytest.mark.spec("001", "FR-014")
@pytest.mark.spec("001", "FR-017")
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


@pytest.mark.spec("001", "FR-017")
def test_identity_mode_passes_when_no_identity_is_configured(
    git: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EMAIL", raising=False)
    git("config", "--unset", "user.email")
    git("config", "user.useConfigOnly", "true")

    assert main(["identity"]) == 0


@pytest.mark.spec("001", "FR-010")
def test_a_clone_can_require_the_private_denylist(
    git: Callable[..., str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    clean = tmp_path / "clean.md"
    clean.write_text("nothing to see\n", encoding="utf-8")

    assert main(["files", str(clean)]) == 0
    git("config", "opscout.requireDenylist", "true")
    capsys.readouterr()
    assert main(["files", str(clean)]) == 1
    assert str(tmp_path / NO_CONFIG / "leak-denylist.txt") in capsys.readouterr().err


@pytest.mark.spec("001", "FR-020")
def test_tracked_mode_checks_every_tracked_file_and_nothing_else(
    git: Callable[..., str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    repo = Path.cwd()
    (repo / "clean.md").write_text("nothing to see\n", encoding="utf-8")
    (repo / "untracked.md").write_text(f"host {HOSTNAME}\n", encoding="utf-8")
    git("add", "clean.md")

    assert main(["tracked"]) == 0
    (repo / "docs").mkdir()
    (repo / "docs" / "notes.md").write_text(f"see {TICKET}\n", encoding="utf-8")
    git("add", "docs")
    assert main(["tracked"]) == 1
    output = capsys.readouterr().out
    assert "docs/notes.md:1: ticket-key" in output
    assert "untracked.md" not in output


@pytest.mark.spec("001", "FR-013")
@pytest.mark.spec("001", "FR-019")
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


@pytest.mark.spec("001", "FR-019")
@pytest.mark.spec("001", "FR-021")
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


@pytest.mark.spec("001", "FR-021")
def test_commits_mode_ignores_deletions(
    git: Callable[..., str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    repo = Path.cwd()
    (repo / "notes.md").write_text(f"host {HOSTNAME}\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "docs: add notes")
    leaky = git("rev-parse", "HEAD").strip()
    git("rm", "-q", "notes.md")
    git("commit", "-q", "-m", "docs: remove the notes")

    assert main(["commits", leaky, "HEAD"]) == 0


@pytest.mark.spec("001", "FR-021")
def test_a_merge_is_checked_against_its_first_parent(
    git: Callable[..., str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    repo = Path.cwd()
    git("commit", "-q", "--allow-empty", "-m", "chore: start")
    trunk = git("branch", "--show-current").strip()
    git("switch", "-q", "-c", "side")
    (repo / "side.md").write_text(f"host {HOSTNAME}\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "docs: add the side notes")
    git("switch", "-q", trunk)
    (repo / "trunk.md").write_text(f"see {TICKET}\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "docs: add the trunk notes")
    git("merge", "-q", "--no-ff", "-m", "chore: merge the side branch", "side")
    merge = git("rev-parse", "HEAD").strip()

    findings = _scan_commits([merge], {}, [])

    assert {(finding.rule, finding.location.split()[-1]) for finding in findings} == {
        ("hostname", "side.md:1")
    }


@pytest.mark.spec("001", "FR-019")
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


@pytest.mark.spec("001", "FR-018")
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


@pytest.mark.spec("001", "FR-015")
def test_files_mode_checks_a_symlink_by_its_own_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    target = tmp_path / "README.md"
    target.write_text("nothing to see\n", encoding="utf-8")
    link = tmp_path / f"link-{TICKET}.md"
    link.symlink_to(target)

    assert main(["files", str(link)]) == 1
    assert "(file name): ticket-key" in capsys.readouterr().out


@pytest.mark.spec("001", "FR-021")
def test_commits_mode_reads_names_git_would_quote(
    git: Callable[..., str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    repo = Path.cwd()
    (repo / ".gitattributes").write_text("*.csv -diff\n", encoding="utf-8")
    (repo / f'q"{TICKET}.csv').write_text(f"host,{HOSTNAME}\n", encoding="utf-8")
    spaced = repo / f"{TICKET} b"
    spaced.mkdir()
    (spaced / "notes.md").write_text("nothing to see\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "docs: add data")

    assert main(["commits", "HEAD"]) == 1
    output = capsys.readouterr().out
    assert f'q"{TICKET}.csv (file name): ticket-key' in output
    assert f'q"{TICKET}.csv:1: hostname' in output
    assert f"{TICKET} b/notes.md (file name): ticket-key" in output


@pytest.mark.spec("001", "FR-018")
def test_pushed_mode_checks_every_local_commit_the_remote_lacks(
    git: Callable[..., str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    git("commit", "-q", "--allow-empty", "-m", "chore: start")
    base = git("rev-parse", "HEAD").strip()
    git("update-ref", "refs/remotes/origin/main", base)
    git("switch", "-q", "-c", "clean")
    git("commit", "-q", "--allow-empty", "-m", "docs: clean")
    clean = git("rev-parse", "HEAD").strip()
    git("switch", "-q", "-c", "leaky", base)
    git("commit", "-q", "--allow-empty", "-m", f"fix: handle {TICKET}")
    # pre-commit passes only the first ref of `git push origin clean leaky`.
    monkeypatch.setenv("PRE_COMMIT_REMOTE_NAME", "origin")
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", base)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", clean)

    assert main(["pushed"]) == 1


@pytest.fixture
def pushing(
    git: Callable[..., str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[..., str]:
    """A scratch repository with one clean commit, set up as pre-commit's pre-push stage."""
    monkeypatch.setenv("OPSCOUT_CONFIG", str(tmp_path / NO_CONFIG))
    git("commit", "-q", "--allow-empty", "-m", "chore: start")
    head = git("rev-parse", "HEAD").strip()
    monkeypatch.setenv("PRE_COMMIT_FROM_REF", head)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", head)
    return git


@pytest.mark.spec("001", "FR-032")
def test_pushed_mode_passes_clean_ref_names(pushing: Callable[..., str]) -> None:
    pushing("branch", "feat/001-example")
    pushing("tag", "v1.2.3")

    assert main(["pushed"]) == 0


@pytest.mark.spec("001", "FR-032")
def test_pushed_mode_checks_local_branch_names(
    pushing: Callable[..., str], capsys: pytest.CaptureFixture[str]
) -> None:
    pushing("branch", f"fix/{TICKET}-login")

    assert main(["pushed"]) == 1
    assert f"ref fix/{TICKET}-login: ticket-key: {TICKET}" in capsys.readouterr().out


@pytest.mark.spec("001", "FR-032")
def test_pushed_mode_checks_tag_names(
    pushing: Callable[..., str], capsys: pytest.CaptureFixture[str]
) -> None:
    pushing("tag", f"release-{HOSTNAME}")

    assert main(["pushed"]) == 1
    assert f"ref release-{HOSTNAME}: hostname" in capsys.readouterr().out


@pytest.mark.spec("001", "FR-032")
def test_pushed_mode_checks_the_remote_name_of_the_pushed_ref(
    pushing: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # git push origin HEAD:refs/heads/fix/<leaky name>, from a clean local branch
    monkeypatch.setenv("PRE_COMMIT_LOCAL_BRANCH", "HEAD")
    monkeypatch.setenv("PRE_COMMIT_REMOTE_BRANCH", f"refs/heads/fix/{TICKET}")

    assert main(["pushed"]) == 1
    output = capsys.readouterr().out
    assert f"ref fix/{TICKET}: ticket-key" in output
    assert output.count("\n") == 1


@pytest.mark.spec("001", "FR-032")
def test_pushed_mode_checks_ref_names_against_the_denylist(
    pushing: Callable[..., str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("OPSCOUT_CONFIG", str(write_denylist(tmp_path / "config")))
    pushing("branch", f"feat/{PRIVATE_TERM}-login")

    assert main(["pushed"]) == 1
    assert f"ref feat/{PRIVATE_TERM}-login: private-term" in capsys.readouterr().out


@pytest.mark.spec("001", "FR-032")
def test_pushed_mode_lets_an_allowlisted_ref_name_through(
    pushing: Callable[..., str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowlist_file = tmp_path / "allow.toml"
    allowlist_file.write_text(
        f'[[allow]]\nvalue = "{TICKET}"\nreason = "A synthetic value in a test."\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(tools.leak_check, "ALLOWLIST_FILE", allowlist_file)
    pushing("branch", f"fix/{TICKET}-login")

    assert main(["pushed"]) == 0


@pytest.mark.spec("001", "FR-030")
def test_every_requirement_has_a_test() -> None:
    required = set(re.findall(r"\*\*(FR-\d{3})\*\*", SPEC_FILE.read_text(encoding="utf-8")))
    proven: set[str] = set()
    for name, test in globals().items():
        if not name.startswith("test_"):
            continue
        for mark in getattr(test, "pytestmark", []):
            if mark.name == "spec" and mark.args[0] == "001":
                proven.add(mark.args[1])
            elif mark.name == "parametrize":
                for value in mark.args[1]:
                    for param_mark in getattr(value, "marks", ()):
                        if param_mark.name == "spec" and param_mark.args[0] == "001":
                            proven.add(param_mark.args[1])

    assert required, "no requirement found in the spec"
    assert sorted(required - proven) == []
    assert sorted(proven - required) == []
