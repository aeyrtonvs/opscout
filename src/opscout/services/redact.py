# SPDX-License-Identifier: Apache-2.0
"""Redaction: secrets and personal data out of any text before it reaches the model.

Each match is replaced by ``[<kind>]`` and counted by kind; the values are never kept
(spec 009, FR-009, research R6). The rules run in order, from the most specific shape to
the most general, so a value is named by its narrowest kind.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

_NAMES = r"password|passwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key"

RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
        ),
    ),
    (
        "connection-string",
        re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@/]+@\S+", re.IGNORECASE),
    ),
    (
        "credential",
        re.compile(
            r"\b(?:A[KS]IA[0-9A-Z]{16}|xox[abpr]-[A-Za-z0-9-]{10,}|xapp-[A-Za-z0-9-]{10,}"
            r"|ghp_[A-Za-z0-9]{30,}|github_pat_\w{20,}|glpat-[\w-]{20,}|sk-[\w-]{20,}"
            r"|ATATT[\w-]{20,}|eyJ[\w-]{8,}\.eyJ[\w-]{8,}\.[\w-]{8,})"
        ),
    ),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
    (
        "phone",
        re.compile(
            r"\+\d[\d\s().-]{7,}\d|\(\d{3}\)\s*\d{3}[-.\s]\d{4}\b|\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"
        ),
    ),
    # Exactly twelve digits, even glued to letters ("Account: 123456789012Threshold").
    ("account-id", re.compile(r"(?<!\d)\d{12}(?!\d)")),
    ("ip", re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")),
)
_ASSIGNMENT = re.compile(
    rf"(?i)((?<![\w.-])[\w.-]*(?:{_NAMES})[\w.-]*\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_SECRET_LIKE = re.compile(r"(?<![\w+=])(?=[\w+=]*\d)(?=[\w+=]*[A-Za-z])[\w+=]{32,}(?![\w+=])")


OPTIONAL_KINDS: Final = frozenset({"account-id", "ip", "email"})
"""The kinds a caller may keep; every other kind is always redacted (spec 011, FR-010)."""


def redact(
    text: str, terms: Sequence[str] = (), *, keep: frozenset[str] = frozenset()
) -> tuple[str, dict[str, int]]:
    """Return the text with every secret, personal datum and term replaced, and the counts.

    ``keep`` names kinds of ``OPTIONAL_KINDS`` to leave as they are; spec 009 keeps none.
    """
    if not keep <= OPTIONAL_KINDS:
        raise ValueError(f"only {sorted(OPTIONAL_KINDS)} may be kept")
    counts: dict[str, int] = {}

    def replace(kind: str, pattern: re.Pattern[str], value: str) -> str:
        def marker(_: re.Match[str]) -> str:
            counts[kind] = counts.get(kind, 0) + 1
            return f"[{kind}]"

        return pattern.sub(marker, value)

    for kind, pattern in RULES[:3]:
        text = replace(kind, pattern, text)

    def assignment(match: re.Match[str]) -> str:
        counts["credential"] = counts.get("credential", 0) + 1
        return f"{match.group(1)}[credential]"

    text = _ASSIGNMENT.sub(assignment, text)
    for kind, pattern in RULES[3:]:
        if kind not in keep:
            text = replace(kind, pattern, text)
    for term in terms:
        # Any case, anywhere: inside a longer word, and with the words of a term joined by
        # spaces, hyphens, underscores or nothing ("Example Corp", "examplecorp_api").
        words = r"[\s_-]*".join(re.escape(word) for word in term.split())
        text = replace("deny-listed", re.compile(rf"(?i){words}"), text)
    return replace("secret-like", _SECRET_LIKE, text), counts


_SECRET_NAME = re.compile(_NAMES, re.IGNORECASE)
_PAIRS: Final = (
    ("Key", "Value"),
    ("Name", "Value"),
    ("ParameterKey", "ParameterValue"),
    ("OutputKey", "OutputValue"),
)
"""Name-and-value shapes AWS returns tags, parameters and outputs in (spec 011, R6)."""


def redact_structure(
    value: object, keep: frozenset[str] = frozenset()
) -> tuple[Any, dict[str, int]]:
    """Redact every string in a JSON-like value, keeping its shape (spec 011, FR-009).

    A key named like a secret hides its value, whatever its type; so does a name-and-value
    pair whose name is. Counts are summed by kind.
    """
    counts: dict[str, int] = {}

    def add(found: Mapping[str, int]) -> None:
        for kind, count in found.items():
            counts[kind] = counts.get(kind, 0) + count

    def walk(item: object) -> object:
        if isinstance(item, str):
            text, found = redact(item, keep=keep)
            add(found)
            return text
        if isinstance(item, Mapping):
            hidden = {
                value_field
                for name_field, value_field in _PAIRS
                if isinstance(item.get(name_field), str)
                and value_field in item
                and _SECRET_NAME.search(item[name_field])
            }
            result: dict[str, object] = {}
            for key, child in item.items():
                if key in hidden or (isinstance(key, str) and _SECRET_NAME.search(key)):
                    add({"secret": 1})
                    result[key] = "[secret]"
                else:
                    result[key] = walk(child)
            return result
        if isinstance(item, list | tuple):
            return [walk(child) for child in item]
        return item

    return walk(value), counts
