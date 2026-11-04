# SPDX-License-Identifier: Apache-2.0
"""The leak check: real data never reaches this public repository (ADR-0015).

Layer 1 looks for generic shapes: account IDs, IP addresses, chat IDs, ticket keys, internal
hostnames and e-mail addresses (gitleaks covers secrets). Layer 2 looks for the terms of a
private deny-list, read from the private configuration directory and never kept here. Layer 3
checks that commit e-mail addresses are GitHub no-reply addresses.

    python -m tools.leak_check files PATH...         # layers 1 and 2, on whole files
    python -m tools.leak_check tracked               # the same, on every tracked file
    python -m tools.leak_check message FILE          # layers 1 and 2, on a commit message
    python -m tools.leak_check identity              # layer 3, on the commit being made
    python -m tools.leak_check commits [BASE] HEAD   # every layer, on each commit (CI)

A value that layer 1 flags but that is not real data goes in ``leak_allowlist.toml``, with
the reason. Layer-2 matches cannot be allow-listed: refine the private deny-list instead.
"""

import argparse
import ipaddress
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from tools._git import commits, git

ALLOWLIST_FILE = Path(__file__).with_name("leak_allowlist.toml")
DENYLIST_NAME = "leak-denylist.txt"


@dataclass(frozen=True)
class Finding:
    """One value that looks like real data, and where it was found."""

    location: str
    rule: str
    value: str

    def render(self, *, redact: bool) -> str:
        """Format the finding; a redacted one keeps only the value's first two characters."""
        shown = f"{self.value[:2]}… (redacted)" if redact else self.value
        return f"{self.location}: {self.rule}: {shown}"


@dataclass(frozen=True)
class Rule:
    """A generic pattern (layer 1) and the test for the values it may match harmlessly."""

    name: str
    pattern: re.Pattern[str]
    harmless: Callable[[str], bool]


DOCUMENTATION_NETWORKS = tuple(
    ipaddress.IPv4Network(network)
    for network in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "127.0.0.0/8")
)
HARMLESS_ADDRESSES = frozenset({"0.0.0.0", "255.255.255.255", "169.254.169.254"})  # noqa: S104
TICKET_LIKE_TERMS = frozenset(
    {"ADR", "CVE", "CWE", "EXAMPLE", "FR", "GHSA", "ISO", "NFR", "PEP", "RFC", "SC", "SHA", "UTF"}
)
RESERVED_DOMAIN = re.compile(
    r"(?:^|\.)(?:example\.(?:com|net|org)|example|invalid|localhost|test)$", re.IGNORECASE
)
NOREPLY = re.compile(
    r"(?:\d+\+)?[A-Za-z0-9-]+(?:\[bot\])?@users\.noreply\.github\.com|noreply@github\.com"
)
# No-reply addresses and the user of SSH remote URLs reach nobody.
HARMLESS_EMAILS = frozenset({"git@github.com", "noreply@github.com"})
NOREPLY_DOMAIN = "users.noreply.github.com"


def _harmless_ip(value: str) -> bool:
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:  # not an address, such as an octet over 255
        return True
    return value in HARMLESS_ADDRESSES or any(
        address in network for network in DOCUMENTATION_NETWORKS
    )


def _harmless_host(value: str) -> bool:
    return any(label.startswith("example") for label in value.lower().split("."))


def _harmless_email(value: str) -> bool:
    domain = value.rsplit("@", 1)[1].lower()
    return (
        value.lower() in HARMLESS_EMAILS
        or domain == NOREPLY_DOMAIN
        or RESERVED_DOMAIN.search(domain) is not None
    )


RULES = (
    Rule("account-id", re.compile(r"\b\d{12}\b"), lambda value: value == "123456789012"),
    Rule(
        "ip-address",
        re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)"),
        _harmless_ip,
    ),
    Rule(
        "chat-id",
        re.compile(r"\b[CDGTUW](?=[A-Z0-9]*\d)[A-Z0-9]{8,10}\b"),
        lambda value: False,
    ),
    Rule(
        "ticket-key",
        re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b(?!\.\d)"),  # not a version: LICENSE-2.0
        lambda value: value.split("-", 1)[0] in TICKET_LIKE_TERMS,
    ),
    Rule(
        "hostname",
        re.compile(
            r"\b(?:[a-z0-9-]+\.)+(?:corp|internal|intranet|lan|local)\b(?!\.?[\w-])",
            re.IGNORECASE,
        ),
        _harmless_host,
    ),
    Rule(
        "e-mail",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        _harmless_email,
    ),
)


class DenylistError(ValueError):
    """The private deny-list holds an entry that is not a valid regular expression."""


def scan_line(
    line: str, location: str, *, allowlist: Mapping[str, str], denylist: Sequence[re.Pattern[str]]
) -> list[Finding]:
    """Return what layers 1 and 2 find in one line."""
    findings = [
        Finding(location, rule.name, match.group())
        for rule in RULES
        for match in rule.pattern.finditer(line)
        if not rule.harmless(match.group()) and match.group() not in allowlist
    ]
    findings.extend(
        Finding(location, "private-term", match.group())
        for pattern in denylist
        for match in pattern.finditer(line)
    )
    return findings


def scan_text(
    text: str, path: str, *, allowlist: Mapping[str, str], denylist: Sequence[re.Pattern[str]]
) -> list[Finding]:
    """Return what layers 1 and 2 find in a text, each finding located as ``path:line``."""
    return [
        finding
        for number, line in enumerate(text.splitlines(), start=1)
        for finding in scan_line(line, f"{path}:{number}", allowlist=allowlist, denylist=denylist)
    ]


def load_allowlist(path: Path) -> dict[str, str]:
    """Read the allow-list: each entry is a ``value`` and the ``reason`` it is not real data."""
    if not path.is_file():
        return {}
    entries = tomllib.loads(path.read_text(encoding="utf-8")).get("allow", [])
    allowlist: dict[str, str] = {}
    for number, entry in enumerate(entries, start=1):
        value, reason = entry.get("value"), entry.get("reason")
        if not isinstance(value, str) or not value:
            raise ValueError(f"{path}: entry {number} needs a value")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{path}: entry {number} needs a reason")
        allowlist[value] = reason
    return allowlist


def find_config_dir(environ: Mapping[str, str], home: Path) -> Path:
    """Locate the private configuration directory: ``OPSCOUT_CONFIG``, else the default."""
    configured = environ.get("OPSCOUT_CONFIG")
    return Path(configured).expanduser() if configured else home / ".config" / "opscout"


def load_denylist(config_dir: Path) -> list[re.Pattern[str]] | None:
    """Read the private deny-list, or return None when the directory has none."""
    path = config_dir / DENYLIST_NAME
    if not path.is_file():
        return None
    patterns: list[re.Pattern[str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        try:
            patterns.append(re.compile(entry, re.IGNORECASE))
        except re.error as error:
            raise DenylistError(f"{path} line {number}: {error}") from error
    return patterns


def check_identity(email: str, role: str) -> Finding | None:
    """Layer 3: a commit e-mail must be a GitHub no-reply address."""
    return None if NOREPLY.fullmatch(email) else Finding(role, "commit-e-mail", email)


HUNK = re.compile(r"@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,\d+)? @@")


def added_lines(diff: str) -> Iterator[tuple[str, int, str]]:
    """Yield ``(path, line number, text)`` for each line a unified diff adds."""
    path: str | None = None
    number = 0
    in_header = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            in_header, path = True, None
        elif in_header and line.startswith("+++ "):
            target = line[4:]
            path = None if target == "/dev/null" else target.removeprefix("b/")
        elif hunk := HUNK.match(line):
            in_header, number = False, int(hunk["start"])
        elif not in_header and path is not None and line.startswith("+"):
            yield path, number, line[1:]
            number += 1


def _read_text(path: Path) -> str | None:
    """Return a file's text, or None for a binary or missing file."""
    try:
        data = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError):
        return None
    return None if b"\0" in data else data.decode("utf-8", errors="replace")


def _scan_files(
    paths: Sequence[Path], allowlist: Mapping[str, str], denylist: Sequence[re.Pattern[str]]
) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        text = _read_text(path)
        if text is not None:
            findings += scan_text(text, str(path), allowlist=allowlist, denylist=denylist)
    return findings


def _scan_identity() -> list[Finding]:
    findings: list[Finding] = []
    for role, variable in (("author", "GIT_AUTHOR_IDENT"), ("committer", "GIT_COMMITTER_IDENT")):
        try:
            ident = git("var", variable)
        except subprocess.CalledProcessError:  # no identity configured, so no commit either
            continue
        match = re.search(r"<([^>]*)>", ident)
        if match and (finding := check_identity(match[1], role)):
            findings.append(finding)
    return findings


def _scan_commits(
    revisions: Sequence[str], allowlist: Mapping[str, str], denylist: Sequence[re.Pattern[str]]
) -> list[Finding]:
    findings: list[Finding] = []
    for sha in commits(revisions):
        commit = f"commit {sha[:12]}"
        author, committer = git("show", "-s", "--format=%ae%n%ce", sha).splitlines()
        for role, email in (("author", author), ("committer", committer)):
            if finding := check_identity(email, f"{commit} {role}"):
                findings.append(finding)
        message = git("show", "-s", "--format=%B", sha)
        findings += scan_text(message, f"{commit} message", allowlist=allowlist, denylist=denylist)
        diff = git(
            "show",
            "--format=",
            "--unified=0",
            "--no-color",
            "--no-ext-diff",
            "--diff-merges=first-parent",
            sha,
        )
        for path, number, text in added_lines(diff):
            findings += scan_line(
                text, f"{commit} {path}:{number}", allowlist=allowlist, denylist=denylist
            )
    return findings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.leak_check",
        description="Check for real data before it reaches this public repository (ADR-0015).",
    )
    parser.add_argument(
        "--redact", action="store_true", help="hide the matched values (always on when CI=true)"
    )
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("files", help="layers 1 and 2 on whole files").add_argument(
        "paths", nargs="*", type=Path
    )
    modes.add_parser("tracked", help="layers 1 and 2 on every tracked file")
    modes.add_parser("message", help="layers 1 and 2 on a commit message").add_argument(
        "path", type=Path
    )
    modes.add_parser("identity", help="layer 3 on the commit being made")
    modes.add_parser("commits", help="every layer on each commit of a range").add_argument(
        "revisions", nargs="+", metavar="[BASE] HEAD"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one mode of the leak check and return 1 when it finds something."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.mode == "commits" and len(args.revisions) > 2:
        parser.error("commits takes [BASE] HEAD")
    try:
        allowlist = load_allowlist(ALLOWLIST_FILE)
        config_dir = find_config_dir(os.environ, Path.home())
        denylist = load_denylist(config_dir)
    except ValueError as error:
        parser.error(str(error))
    if denylist is None and args.mode != "identity":
        print(
            f"leak check: no private deny-list at {config_dir / DENYLIST_NAME}; "
            "layer 2 was skipped (CONTRIBUTING.md)",
            file=sys.stderr,
        )
    terms = denylist or []

    findings: list[Finding]
    if args.mode == "files":
        findings = _scan_files(args.paths, allowlist, terms)
    elif args.mode == "tracked":
        tracked = [Path(name) for name in git("ls-files", "-z").split("\0") if name]
        findings = _scan_files(tracked, allowlist, terms)
    elif args.mode == "message":
        findings = _scan_files([args.path], allowlist, terms)
    elif args.mode == "identity":
        findings = _scan_identity()
    else:
        findings = _scan_commits(args.revisions, allowlist, terms)

    for finding in findings:
        # CI logs are public, so a run there never prints the values it found.
        print(finding.render(redact=args.redact or os.environ.get("CI") == "true"))
    if findings:
        print(
            "\nThis looks like real data, which this public repository must never hold "
            "(AGENTS.md, rule 1). Replace it with a reserved value. If it is not real data, add "
            "it to tools/leak_allowlist.toml with the reason (private terms cannot be "
            "allow-listed).",
            file=sys.stderr,
        )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
