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
_IGNORED = frozenset({"README.md", ".DS_Store"})


class TreeError(Exception):
    """A tree that cannot be read: a missing directory or a file that does not parse."""


def _package() -> Traversable:
    return files("opscout").joinpath("data", "identity")


class _DuplicateKeyError(ValueError):
    """A mapping repeats a key; which value a consumer keeps is not something to rely on."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


class _UniqueKeyLoader(yaml.SafeLoader):
    """A safe loader that refuses a mapping with a repeated key."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


def _parse(relative: str, text: str) -> Any:
    if relative.endswith(".json"):
        try:
            return json.loads(text, object_pairs_hook=_unique_pairs)
        except json.JSONDecodeError as error:
            raise TreeError(f"{relative}:{error.lineno}: {error.msg}") from None
        except _DuplicateKeyError as error:
            raise TreeError(f"{relative}: duplicate key {error}") from None
    try:
        return list(yaml.load_all(text, Loader=_UniqueKeyLoader))
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        line = mark.line + 1 if mark is not None else 0
        raise TreeError(f"{relative}:{line}: {error.problem or error}") from None
    except yaml.YAMLError as error:
        raise TreeError(f"{relative}: {error}") from None


def read_tree(directory: Path) -> Tree:
    """Parse every file under ``directory``.

    Skipped: anything under a dot entry at the top (such as ``.git``), ``.DS_Store`` and
    ``README.md`` anywhere. Every other file is kept; one with another suffix, or a hidden
    file inside the documents, is kept as ``None`` so the check reports it as not part of
    the identity.
    """
    if not directory.is_dir():
        raise TreeError(f"{directory}: no such directory")
    parsed: dict[str, Any] = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        if path.is_dir() or path.name in _IGNORED:
            continue
        if path.relative_to(directory).parts[0].startswith("."):
            continue
        if path.name.startswith(".") or not path.name.endswith(_SUFFIXES):
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
