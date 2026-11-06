# SPDX-License-Identifier: Apache-2.0
"""Read identity trees and the package's identity records (spec 010; research R7).

The package owns the catalog, the managed-policy copies, the capability declarations, the
reviewed guardrail list and the reference tree. A checked directory only supplies its
editable documents, so an instantiated copy cannot weaken what it is proved against.
"""

import json
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

import yaml

from opscout.core.identity import (
    Catalog,
    Records,
    Tree,
    managed_policy,
    parse_capabilities,
    parse_guardrail,
)

EDITABLE = ("aws", "ssm", "eks", "kubernetes")
_SUFFIXES = (".json", ".yaml", ".yml")
_IGNORED = frozenset({"README.md"})


class TreeError(Exception):
    """A tree that cannot be read: a missing directory or a file that does not parse."""


def _package() -> Traversable:
    return files("opscout").joinpath("data", "identity")


def _parse(relative: str, text: str) -> Any:
    if relative.endswith(".json"):
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise TreeError(f"{relative}:{error.lineno}: {error.msg}") from None
    try:
        return list(yaml.safe_load_all(text))
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        line = mark.line + 1 if mark is not None else 0
        raise TreeError(f"{relative}:{line}: {error.problem or error}") from None
    except yaml.YAMLError as error:
        raise TreeError(f"{relative}: {error}") from None


def read_tree(directory: Path) -> Tree:
    """Parse every file under ``directory``; dotfiles and ``README.md`` are skipped.

    A file with another suffix is kept as ``None`` so the check reports it as not part of
    the identity.
    """
    if not directory.is_dir():
        raise TreeError(f"{directory}: no such directory")
    parsed: dict[str, Any] = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        if path.is_dir() or path.name in _IGNORED:
            continue
        if any(part.startswith(".") for part in path.relative_to(directory).parts):
            continue
        if not path.name.endswith(_SUFFIXES):
            parsed[relative] = None
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise TreeError(f"{relative}: cannot be read ({error})") from None
        parsed[relative] = _parse(relative, text)
    return Tree(parsed)


def _walk(node: Traversable, prefix: str) -> list[tuple[str, Traversable]]:
    found: list[tuple[str, Traversable]] = []
    for child in sorted(node.iterdir(), key=lambda item: item.name):
        relative = f"{prefix}{child.name}"
        if child.is_dir():
            found += _walk(child, f"{relative}/")
        elif child.name.endswith(_SUFFIXES):
            found.append((relative, child))
    return found


def reference_files() -> list[tuple[str, str]]:
    """The editable reference documents, as ``(relative path, text)``."""
    root = _package()
    return [
        (relative, item.read_text(encoding="utf-8"))
        for top in EDITABLE
        if root.joinpath(top).is_dir()
        for relative, item in _walk(root.joinpath(top), f"{top}/")
    ]


def _json(name: str) -> Any:
    return json.loads(_package().joinpath(*name.split("/")).read_text(encoding="utf-8"))


def load_records() -> Records:
    """Load the package's identity records."""
    reference = Tree({relative: _parse(relative, text) for relative, text in reference_files()})
    return Records(
        catalog=Catalog.from_data(_json("catalog.json")),
        view_only=managed_policy(_json("managed/ViewOnlyAccess.json")),
        read_only=managed_policy(_json("managed/ReadOnlyAccess.json")),
        capabilities=parse_capabilities(_json("capabilities.json")),
        guardrail=parse_guardrail(_json("guardrail-actions.json")),
        reference=reference,
    )


def export_tree(directory: Path) -> list[str]:
    """Write the editable reference tree into ``directory``; refuse to overwrite anything."""
    documents = reference_files()
    clashes = [relative for relative, _ in documents if (directory / relative).exists()]
    if clashes:
        raise TreeError(f"{directory}: already holds {', '.join(clashes)}; nothing written")
    for relative, text in documents:
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return [relative for relative, _ in documents]
