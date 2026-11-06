# SPDX-License-Identifier: Apache-2.0
"""The read-only identity's model and policy evaluator (spec 010; research R1-R3).

Everything here is pure: policies arrive parsed from JSON, the catalog from its recorded
data. The evaluator is sound by construction for what it proves. A statement with a
``Condition`` never counts as a deny and always counts as a possible allow, and anything it
cannot read fails as "cannot prove" instead of passing.
"""

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Literal

POLICY_VERSION = "2012-10-17"
_STATEMENT_KEYS = frozenset(
    {"Sid", "Effect", "Action", "NotAction", "Resource", "NotResource", "Condition"}
)
WRITE_FLAGS = frozenset("wpt")

Effect = Literal["Allow", "Deny"]


class CannotProveError(Exception):
    """A document uses something the check cannot evaluate, so it proves nothing."""

    def __init__(self, ref: str, message: str) -> None:
        super().__init__(f"{ref}: {message}")
        self.ref = ref
        self.message = message


@cache
def wildcard(pattern: str, *, case_sensitive: bool) -> re.Pattern[str]:
    """Compile an IAM wildcard pattern: ``*`` is any run, ``?`` one character."""
    body = "".join(
        ".*" if char == "*" else "." if char == "?" else re.escape(char) for char in pattern
    )
    return re.compile(f"^{body}$", 0 if case_sensitive else re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class Statement:
    """One statement, as the evaluator needs it."""

    ref: str
    effect: Effect
    actions: tuple[str, ...]
    not_action: bool
    resources: tuple[str, ...]
    not_resource: bool
    conditional: bool

    def matches_action(self, action: str) -> bool:
        """Whether the statement's action element covers ``action``."""
        hit = any(wildcard(p, case_sensitive=False).match(action) for p in self.actions)
        return hit != self.not_action

    def matches_resource(self, resource: str) -> bool:
        """Whether the statement's resource element covers ``resource``."""
        hit = any(wildcard(p, case_sensitive=True).match(resource) for p in self.resources)
        return hit != self.not_resource

    @property
    def everywhere(self) -> bool:
        """Whether the statement applies to every resource, unconditionally."""
        return not self.conditional and not self.not_resource and "*" in self.resources


@dataclass(frozen=True)
class Policy:
    """A parsed identity policy."""

    name: str
    statements: tuple[Statement, ...]


@dataclass(frozen=True)
class ManagedPolicy:
    """A recorded copy of an AWS-managed policy."""

    arn: str
    version: str
    fetched: str
    policy: Policy


def _strings(ref: str, key: str, value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise CannotProveError(ref, f"{key} must be a string or a non-empty list of strings")


def _one_of(ref: str, raw: Mapping[str, Any], key: str) -> tuple[tuple[str, ...], bool]:
    plain, negated = key, f"Not{key}"
    if (plain in raw) == (negated in raw):
        raise CannotProveError(ref, f"needs exactly one of {plain} and {negated}")
    if plain in raw:
        return _strings(ref, plain, raw[plain]), False
    return _strings(ref, negated, raw[negated]), True


def _statement(name: str, index: int, raw: object) -> Statement:
    ref = f"{name}#{index}"
    if not isinstance(raw, dict):
        raise CannotProveError(ref, "a statement must be an object")
    sid = raw.get("Sid")
    if isinstance(sid, str) and sid:
        ref = f"{name}#{sid}"
    unknown = sorted(set(raw) - _STATEMENT_KEYS)
    if unknown:
        raise CannotProveError(ref, f"uses {', '.join(unknown)}, which the check cannot prove")
    effect = raw.get("Effect")
    if effect not in ("Allow", "Deny"):
        raise CannotProveError(ref, "Effect must be Allow or Deny")
    actions, not_action = _one_of(ref, raw, "Action")
    resources, not_resource = _one_of(ref, raw, "Resource")
    return Statement(
        ref=ref,
        effect=effect,
        actions=actions,
        not_action=not_action,
        resources=resources,
        not_resource=not_resource,
        conditional="Condition" in raw,
    )


def parse_policy(name: str, data: object) -> Policy:
    """Parse an identity policy, refusing anything the evaluator cannot prove."""
    if not isinstance(data, dict):
        raise CannotProveError(name, "a policy must be a JSON object")
    unknown = sorted(set(data) - {"Version", "Statement", "Id"})
    if unknown:
        raise CannotProveError(name, f"uses {', '.join(unknown)}, which the check cannot prove")
    if data.get("Version") != POLICY_VERSION:
        raise CannotProveError(name, f"Version must be {POLICY_VERSION}")
    if "Statement" not in data:
        raise CannotProveError(name, "has no Statement")
    raw = data["Statement"]
    items = raw if isinstance(raw, list) else [raw]
    return Policy(name, tuple(_statement(name, i, item) for i, item in enumerate(items)))


@dataclass(frozen=True)
class Catalog:
    """AWS's actions with their access-level flags, keyed by lower-case ``service:action``."""

    source: str
    fetched: str
    services: Mapping[str, str]
    _flags: Mapping[str, str] = field(repr=False)
    _names: Mapping[str, str] = field(repr=False)
    _by_service: Mapping[str, tuple[str, ...]] = field(repr=False)

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> "Catalog":
        """Build a catalog from its recorded JSON form (data-model.md)."""
        flags: dict[str, str] = {}
        names: dict[str, str] = {}
        by_service: dict[str, tuple[str, ...]] = {}
        versions: dict[str, str] = {}
        for prefix, service in data["services"].items():
            versions[prefix] = service["version"]
            keys = []
            for action, level in service["actions"].items():
                key = f"{prefix}:{action}".lower()
                flags[key] = level
                names[key] = f"{prefix}:{action}"
                keys.append(key)
            by_service[prefix.lower()] = tuple(keys)
        return cls(data["source"], data["fetched"], versions, flags, names, by_service)

    def __len__(self) -> int:
        return len(self._flags)

    def __iter__(self) -> Iterator[str]:
        return iter(self._flags)

    def flags(self, action: str) -> str | None:
        """The action's flags, or ``None`` when the catalog does not know it."""
        return self._flags.get(action.lower())

    def name(self, action: str) -> str | None:
        """The action's name as AWS spells it, or ``None`` when unknown."""
        return self._names.get(action.lower())

    def is_write(self, action: str) -> bool:
        """Whether AWS classifies the action as a write, permissions change or tagging."""
        return bool(set(self._flags.get(action.lower(), "")) & WRITE_FLAGS)

    def is_data_plane(self, action: str) -> bool:
        """Whether AWS classifies the action as data plane."""
        return "d" in self._flags.get(action.lower(), "")

    def expand(self, pattern: str) -> set[str]:
        """Every catalog key a single action pattern covers."""
        service, _, action = pattern.lower().partition(":")
        if pattern == "*":
            return set(self._flags)
        if not action:
            return set()
        if "*" in service or "?" in service:
            prefix = wildcard(service, case_sensitive=False)
            services = [s for s in self._by_service if prefix.match(s)]
        else:
            services = [service] if service in self._by_service else []
        matcher = wildcard(f"*:{action}", case_sensitive=False)
        return {key for s in services for key in self._by_service[s] if matcher.match(key)}

    def covered(self, statement: Statement) -> set[str]:
        """Every catalog key the statement's action element covers."""
        keys: set[str] = set()
        for pattern in statement.actions:
            keys |= self.expand(pattern)
        return set(self._flags) - keys if statement.not_action else keys


@dataclass(frozen=True)
class Identity:
    """One identity: its attached policies and its permissions boundary."""

    name: str
    policies: tuple[Policy, ...]
    boundary: Policy

    def statements(self) -> Iterable[Statement]:
        """Every statement of the attached policies, then the boundary's."""
        for policy in (*self.policies, self.boundary):
            yield from policy.statements


FindingKind = Literal[
    "secret-allowed",
    "write-allowed",
    "data-allowed",
    "exception-too-wide",
    "read-missing",
    "undeclared-grant",
    "unknown-action",
    "cannot-prove",
    "too-large",
    "host-document",
    "host-pattern",
    "cluster",
    "layout",
    "placeholder",
]


@dataclass(frozen=True)
class Finding:
    """One reason the check fails."""

    kind: FindingKind
    message: str

    def __str__(self) -> str:
        return f"{self.kind}: {self.message}"


@dataclass(frozen=True)
class Report:
    """The check's result: summary lines and findings; it passes with no findings."""

    summary: tuple[str, ...]
    findings: tuple[Finding, ...]

    @property
    def passed(self) -> bool:
        """Whether nothing failed."""
        return not self.findings


@dataclass(frozen=True)
class Capability:
    """A declared group of read permissions (``capabilities.json``, FR-004)."""

    name: str
    purpose: str
    agents: tuple[str, ...]
    identity: Literal["readonly", "hosts"]
    optional: bool
    grant: Literal["managed", "actions"]
    actions: tuple[str, ...]
    reads: tuple[str, ...]


@dataclass(frozen=True)
class GuardEntry:
    """One reviewed guardrail entry (``guardrail-actions.json``, research R4)."""

    group: str
    action: str
    resource: str
    why: str


@dataclass(frozen=True)
class Tree:
    """An identity's editable documents, parsed, by path relative to the tree's root.

    JSON files hold their object; YAML files hold the list of their documents.
    """

    files: Mapping[str, Any]


@dataclass(frozen=True)
class Records:
    """What the package owns and a checked tree can never override (research R7)."""

    catalog: Catalog
    view_only: ManagedPolicy
    read_only: ManagedPolicy
    capabilities: tuple[Capability, ...]
    guardrail: tuple[GuardEntry, ...]
    reference: Tree


def parse_capabilities(data: object) -> tuple[Capability, ...]:
    """Parse ``capabilities.json``; a malformed record is a packaging bug."""
    if not isinstance(data, list):
        raise ValueError("capabilities.json must be a list")
    return tuple(
        Capability(
            name=item["name"],
            purpose=item["purpose"],
            agents=tuple(item["agents"]),
            identity=item["identity"],
            optional=bool(item["optional"]),
            grant=item["grant"],
            actions=tuple(item.get("actions", ())),
            reads=tuple(item["reads"]),
        )
        for item in data
    )


def parse_guardrail(data: object) -> tuple[GuardEntry, ...]:
    """Parse ``guardrail-actions.json``: groups of entries."""
    if not isinstance(data, dict):
        raise ValueError("guardrail-actions.json must be an object of groups")
    return tuple(
        GuardEntry(group, entry["action"], entry.get("resource", "*"), entry["why"])
        for group, entries in data.items()
        for entry in entries
    )


def managed_policy(data: Mapping[str, Any]) -> ManagedPolicy:
    """Build a managed-policy copy from its recorded form."""
    name = data["arn"].rsplit("/", 1)[1]
    return ManagedPolicy(
        data["arn"], data["version"], data["fetched"], parse_policy(name, data["document"])
    )


ADDED = "Allow * (added)"


def with_allow_all(identity: Identity) -> Identity:
    """The identity with ``Allow *`` attached: anything someone could add by mistake (R3)."""
    allow_all = Statement(
        ref=f"{ADDED}#0",
        effect="Allow",
        actions=("*",),
        not_action=False,
        resources=("*",),
        not_resource=False,
        conditional=False,
    )
    return Identity(
        identity.name, (*identity.policies, Policy(ADDED, (allow_all,))), identity.boundary
    )


def _matching(statements: Iterable[Statement], action: str, resource: str) -> list[Statement]:
    return [s for s in statements if s.matches_action(action) and s.matches_resource(resource)]


def _policy_statements(identity: Identity) -> list[Statement]:
    return [s for policy in identity.policies for s in policy.statements]


def _allowed_one(identity: Identity, action: str, resource: str) -> tuple[bool, str | None]:
    for statement in _matching(identity.statements(), action, resource):
        if statement.effect == "Deny":
            return False, statement.ref
    for name, statements in (
        (identity.name, _policy_statements(identity)),
        (identity.boundary.name, list(identity.boundary.statements)),
    ):
        allows = [s for s in _matching(statements, action, resource) if s.effect == "Allow"]
        if not allows:
            return False, f"no allow in {name}"
        if all(s.conditional for s in allows):
            return False, allows[0].ref
    return True, None


def proves_allowed(identity: Identity, action: str, *resources: str) -> tuple[bool, str | None]:
    """Whether every one of the requests is certainly allowed; else what stands in the way."""
    for resource in resources:
        allowed, reason = _allowed_one(identity, action, resource)
        if not allowed:
            return False, reason
    return True, None


def _denied_one(identity: Identity, action: str, resource: str) -> tuple[bool, str]:
    for statement in _matching(identity.statements(), action, resource):
        if statement.effect == "Deny" and not statement.conditional:
            return True, statement.ref
    first = ""
    for name, statements in (
        (identity.name, _policy_statements(identity)),
        (identity.boundary.name, list(identity.boundary.statements)),
    ):
        allows = [s for s in _matching(statements, action, resource) if s.effect == "Allow"]
        if not allows:
            return True, f"no allow in {name}"
        first = first or allows[0].ref
    return False, first


def proves_denied(identity: Identity, action: str, *resources: str) -> tuple[bool, str]:
    """Whether the request is certainly denied (one denied resource is enough)."""
    reason = ""
    for resource in resources:
        denied, reason = _denied_one(identity, action, resource)
        if denied:
            return True, reason
    return False, reason


class Analysis:
    """Catalog-wide questions about one identity, over every resource at once."""

    def __init__(self, identity: Identity, catalog: Catalog) -> None:
        self.identity = identity
        self.catalog = catalog
        self._denies = [
            (s.ref, catalog.covered(s))
            for s in identity.statements()
            if s.effect == "Deny" and s.everywhere
        ]
        self._allows = [
            (s.ref, catalog.covered(s)) for s in _policy_statements(identity) if s.effect == "Allow"
        ]
        bounded: set[str] = set()
        for statement in identity.boundary.statements:
            if statement.effect == "Allow":
                bounded |= catalog.covered(statement)
        self._bounded = bounded

    def denied_everywhere(self, key: str) -> str | None:
        """Why ``key`` is denied on every resource, or ``None`` when it may be allowed."""
        for ref, keys in self._denies:
            if key in keys:
                return ref
        if not any(key in keys for _, keys in self._allows):
            return f"no allow in {self.identity.name}"
        if key not in self._bounded:
            return f"no allow in {self.identity.boundary.name}"
        return None

    def may_allow(self, key: str) -> str | None:
        """The first statement that may allow ``key`` somewhere, or ``None``."""
        if self.denied_everywhere(key) is not None:
            return None
        return next(ref for ref, keys in self._allows if key in keys)

    def allowed_somewhere(self) -> set[str]:
        """Every catalog key that may be allowed on some resource."""
        candidates: set[str] = set()
        for _, keys in self._allows:
            candidates |= keys
        return {key for key in candidates & self._bounded if self.denied_everywhere(key) is None}
