# SPDX-License-Identifier: Apache-2.0
"""Find and read the configuration, and report every problem with its place (spec 002).

Everything here is pure: the command line, the environment, the home directory and the
file's bytes are passed in, so the entrypoints do the I/O.

The YAML is composed, never constructed: PyYAML's safe composer builds a node graph, and
``_Reader`` turns it into plain data while it records where each key and value starts,
refuses duplicate keys, tags that are not plain data and the merge key, and stops at
``MAX_NODES`` nodes (aliases expanded) or ``MAX_DEPTH`` levels. Problem messages are built
from the kind of error, never from the value found (FR-017).
"""

import codecs
import enum
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from opscout.core.config import (
    MIGRATION_NOTES,
    RETIRED_VERSIONS,
    SCHEMA_VERSION,
    Configuration,
    InvalidConfigError,
    Problem,
)

CONFIG_FILE: Final = "config.yaml"
ENV_VAR: Final = "OPSCOUT_CONFIG"
MAX_BYTES: Final = 1024 * 1024
MAX_NODES: Final = 10_000
MAX_DEPTH: Final = 100

DOCUMENT: Final = "(document)"
TOP_LEVEL: Final = "(top level)"

_YAML: Final = "tag:yaml.org,2002:"
_PLAIN_SCALARS: Final = frozenset(
    f"{_YAML}{name}" for name in ("str", "int", "float", "bool", "null", "timestamp")
)
_STR: Final = f"{_YAML}str"
_MAP: Final = f"{_YAML}map"
_SEQ: Final = f"{_YAML}seq"
_MERGE: Final = f"{_YAML}merge"
# YAML 1.1 forms that YAML 1.2, which editors follow, reads differently (FR-015).
_FORMS: Final = {
    f"{_YAML}int": (
        re.compile(r"[-+]?(0|[1-9][0-9]*)"),
        "write integers in plain decimal digits; YAML 1.2 editors read this form differently",
    ),
    f"{_YAML}bool": (
        re.compile(r"true|True|TRUE|false|False|FALSE"),
        "write booleans as true or false; quote the value if it is text",
    ),
}
_PLAIN_KEY: Final = re.compile(r"[^\s.\[\]\"'\\]+")
MAX_SHOWN_KEY: Final = 64
_QUOTED: Final = re.compile(r"'[^']*'|\"[^\"]*\"")

_UNKNOWN_KEY: Final = "unknown key; it may be a typo or come from a newer opscout"
_EXPECTED: Final = {
    "int_type": "expected an integer",
    "int_from_float": "expected an integer",
    "float_type": "expected a number",
    "string_type": "expected a string",
    "bool_type": "expected true or false",
    "dict_type": "expected a mapping",
    "model_type": "expected a mapping",
    "model_attributes_type": "expected a mapping",
    "list_type": "expected a list",
    "tuple_type": "expected a list",
    "date_type": "expected a date",
    "datetime_type": "expected a date and time",
    "none_required": "expected null",
}


class Source(enum.StrEnum):
    """Where the configuration directory came from (FR-001)."""

    FLAG = "from --config"
    ENV = f"from {ENV_VAR}"
    DEFAULT = "default"


@dataclass(frozen=True)
class ConfigLocation:
    """The configuration directory and its source."""

    directory: Path
    source: Source

    def describe(self) -> str:
        """Return the directory and its source, as the validate command prints them."""
        return f"{self.directory} ({self.source})"


def resolve_config_dir(flag: Path | None, environ: Mapping[str, str], home: Path) -> ConfigLocation:
    """Resolve the directory: the flag, then a non-empty ``OPSCOUT_CONFIG``, then the default."""
    if flag is not None:
        return ConfigLocation(_expand(flag, home), Source.FLAG)
    configured = environ.get(ENV_VAR, "")
    if configured:
        return ConfigLocation(_expand(Path(configured), home), Source.ENV)
    return ConfigLocation(home / ".config" / "opscout", Source.DEFAULT)


def _expand(path: Path, home: Path) -> Path:
    """Expand a leading ``~`` against ``home``, which the shell does not do inside ``--x=~``."""
    if path.parts and path.parts[0] == "~":
        return home.joinpath(*path.parts[1:])
    return path


@dataclass
class Reader:
    """Where each key and value of a document starts, and what was refused while reading."""

    file: str
    values: dict[tuple[str | int, ...], tuple[int, int]] = field(default_factory=dict)
    keys: dict[tuple[str | int, ...], tuple[int, int]] = field(default_factory=dict)
    refused: list[Problem] = field(default_factory=list)
    replaced: set[tuple[str | int, ...]] = field(default_factory=set)
    nodes: int = 0

    def problem(self, place: tuple[int, int], path: str, message: str) -> Problem:
        """Return a problem at a 1-based ``(line, column)``."""
        return Problem(self.file, place[0], place[1], path, message)


class _StopError(Exception):
    """The document is refused as a whole."""

    def __init__(self, problem: Problem) -> None:
        super().__init__(problem.message)
        self.problem = problem


def read_yaml(data: bytes, file: str) -> tuple[Any, Reader]:
    """Return the plain data of one YAML document and where each part of it starts.

    Raises ``InvalidConfigError`` when the bytes are not one plain YAML document.
    """
    reader = Reader(file)
    if len(data) > MAX_BYTES:
        raise _invalid(reader.problem((1, 1), DOCUMENT, "the file is larger than 1 MiB"))
    body = data.removeprefix(codecs.BOM_UTF8)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as error:
        before = body[: error.start]
        line_start = before.rfind(b"\n") + 1
        column = len(body[line_start : error.start].decode("utf-8", errors="replace")) + 1
        place = (before.count(b"\n") + 1, column)
        raise _invalid(reader.problem(place, DOCUMENT, "the file is not valid UTF-8")) from None
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.reader.ReaderError as error:
        before_text = text[: error.position]
        place = (before_text.count("\n") + 1, error.position - before_text.rfind("\n"))
        message = "not valid YAML: the file holds a character YAML does not allow"
        raise _invalid(reader.problem(place, DOCUMENT, message)) from None
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        place = (mark.line + 1, mark.column + 1) if mark else (1, 1)
        detail = _QUOTED.sub(_hide_quoted, error.problem or "")
        message = f"not valid YAML: {detail}" if detail else "not valid YAML"
        raise _invalid(reader.problem(place, DOCUMENT, message)) from None
    except RecursionError:
        raise _invalid(_too_deep(reader)) from None
    if node is None:
        message = "the file is empty; it must hold a mapping with schema_version"
        raise _invalid(reader.problem((1, 1), DOCUMENT, message))
    if not isinstance(node, yaml.MappingNode) or node.tag != _MAP:
        raise _invalid(
            reader.problem(_start(node), TOP_LEVEL, "the top level must be a mapping of keys")
        )
    constructor = yaml.SafeLoader("")
    try:
        document = _build(node, (), reader, constructor)
    except _StopError as stop:
        raise _invalid(stop.problem) from None
    return document, reader


def _build(
    node: yaml.Node,
    path: tuple[str | int, ...],
    reader: Reader,
    constructor: yaml.SafeLoader,
) -> Any:
    reader.nodes += 1
    if reader.nodes > MAX_NODES:
        message = f"the document expands to more than {MAX_NODES:,} nodes"
        raise _StopError(reader.problem((1, 1), DOCUMENT, message))
    if len(path) > MAX_DEPTH:
        raise _StopError(_too_deep(reader))
    reader.values.setdefault(path, _start(node))
    if isinstance(node, yaml.MappingNode) and node.tag == _MAP:
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag == _MERGE:
                _refuse(reader, path, key_node, "merge keys (<<) are not supported")
                continue
            if not isinstance(key_node, yaml.ScalarNode) or key_node.tag != _STR:
                _refuse(reader, path, key_node, "a key must be a string")
                continue
            key = constructor.construct_object(key_node)
            if key in mapping:
                _refuse(reader, (*path, key), key_node, "duplicate key")
                continue
            reader.keys[(*path, key)] = _start(key_node)
            mapping[key] = _build(value_node, (*path, key), reader, constructor)
        return mapping
    if isinstance(node, yaml.SequenceNode) and node.tag == _SEQ:
        return [
            _build(item, (*path, index), reader, constructor)
            for index, item in enumerate(node.value)
        ]
    if isinstance(node, yaml.ScalarNode) and node.tag in _PLAIN_SCALARS:
        form = _FORMS.get(node.tag)
        if form is not None and not form[0].fullmatch(node.value):
            _refuse(reader, path, node, form[1])
            reader.replaced.add(path)
            return None
        try:
            return constructor.construct_object(node)
        except Exception:  # PyYAML raises ValueError and others for a value like !!int abc
            _refuse(reader, path, node, "this value cannot be read as its tag says")
            reader.replaced.add(path)
            return None
    _refuse(reader, path, node, "this tag is not allowed; only plain data is read")
    reader.replaced.add(path)
    return None


def _hide_quoted(match: re.Match[str]) -> str:
    """Hide text the parser quotes from the file; keep one-character tokens and ``<stream end>``."""
    inner = match.group(0)[1:-1]
    if len(inner) <= 1 or (inner.startswith("<") and inner.endswith(">")):
        return match.group(0)
    return "…"


def _refuse(reader: Reader, path: tuple[str | int, ...], node: yaml.Node, message: str) -> None:
    reader.refused.append(reader.problem(_start(node), _dotted(path), message))


def _start(node: yaml.Node) -> tuple[int, int]:
    return node.start_mark.line + 1, node.start_mark.column + 1


def _too_deep(reader: Reader) -> Problem:
    return reader.problem(
        (1, 1), DOCUMENT, f"the document is nested deeper than {MAX_DEPTH} levels"
    )


def _invalid(problem: Problem) -> InvalidConfigError:
    return InvalidConfigError((problem,))


def _dotted(path: tuple[str | int, ...]) -> str:
    """Return a key path such as ``section.items[1]``, or ``(top level)``."""
    text = ""
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{_shown(part)}" if text else _shown(part)
    return text or TOP_LEVEL


def _shown(key: str) -> str:
    """Return a key as printed: bare when it is plain text, else quoted and escaped (FR-017).

    Escaping keeps line breaks and terminal control sequences in a key from reaching the
    output, and long keys are cut short.
    """
    shown, cut = key[:MAX_SHOWN_KEY], "…" if len(key) > MAX_SHOWN_KEY else ""
    if _PLAIN_KEY.fullmatch(shown) and shown.isprintable():
        return shown + cut
    return json.dumps(shown) + cut


def validate[M: BaseModel](document: Any, reader: Reader, model: type[M]) -> M:
    """Validate plain data against a model and locate every problem in the file.

    The problems found while reading come first in importance: a value the reader refused
    and replaced gets no second problem from the model, but every other part of the
    document is still validated, so one run reports everything (FR-016).
    """
    problems = list(reader.refused)
    try:
        result = model.model_validate(document)
    except ValidationError as error:
        for detail in error.errors(include_url=False, include_input=False):
            where = _document_path(detail["loc"], reader, keep_last=False)
            if not any(where[: len(path)] == path for path in reader.replaced):
                problems.append(_locate(detail, reader))
    else:
        if not problems:
            return result
    raise InvalidConfigError(tuple(sorted(problems)))


def _locate(detail: ErrorDetails, reader: Reader) -> Problem:
    kind = detail["type"]
    if kind in ("extra_forbidden", "missing"):
        *parent, key = _document_path(detail["loc"], reader, keep_last=True)
        path = (*parent, key)
        if kind == "extra_forbidden" and path in reader.keys:
            return reader.problem(reader.keys[path], _dotted(path), _UNKNOWN_KEY)
        message = _UNKNOWN_KEY if kind == "extra_forbidden" else "required key is missing"
        return reader.problem(reader.values[tuple(parent)], _dotted(path), message)
    path = _document_path(detail["loc"], reader, keep_last=False)
    if detail["loc"][-1:] == ("[key]",) and path in reader.keys:
        # A mapping key that breaks its rule (such as a format name) is located at the key.
        return reader.problem(reader.keys[path], _dotted(path), _message(detail))
    return reader.problem(reader.values[path], _dotted(path), _message(detail))


def _document_path(
    loc: tuple[str | int, ...], reader: Reader, *, keep_last: bool
) -> tuple[str | int, ...]:
    """Return the part of an error location that names keys and items of the document.

    Pydantic adds steps of its own, such as the member type of a union (``choice.int``);
    they are dropped. With ``keep_last``, the last step is kept: it names the missing or
    unknown key itself.
    """
    steps = list(loc)
    last = steps.pop() if keep_last and steps else None
    path: tuple[str | int, ...] = ()
    for step in steps:
        if (*path, step) in reader.values:
            path = (*path, step)
    return (*path, last) if last is not None else path


def _message(detail: ErrorDetails) -> str:
    """Describe what was expected, from the kind of error and never from the input."""
    kind = detail["type"]
    context = detail.get("ctx", {})
    if kind in _EXPECTED:
        return _EXPECTED[kind]
    if kind == "literal_error":
        return f"expected {context.get('expected', 'one of the allowed values')}"
    if kind == "string_too_short":
        return f"expected at least {context.get('min_length')} character(s)"
    if kind == "string_too_long":
        return f"expected at most {context.get('max_length')} characters"
    bounds = {
        "greater_than": ("more than", "gt"),
        "greater_than_equal": ("at least", "ge"),
        "less_than": ("less than", "lt"),
        "less_than_equal": ("at most", "le"),
    }
    if kind in bounds:
        words, key = bounds[kind]
        return f"expected {words} {context.get(key)}"
    if kind in ("too_long", "too_short"):
        words, key = ("at most", "max_length") if kind == "too_long" else ("at least", "min_length")
        return f"expected {words} {context.get(key)} item(s)"
    if kind == "string_pattern_mismatch":
        return f"expected text matching {context.get('pattern')}"
    return "not a valid value here"


def parse_config(
    data: bytes,
    file: str,
    *,
    supported: int = SCHEMA_VERSION,
    retired: Mapping[int, str] = RETIRED_VERSIONS,
) -> Configuration:
    """Read and validate a configuration file's bytes.

    Raises ``InvalidConfigError`` with every problem found, in file order. A
    ``schema_version`` of another major version is the only problem reported (FR-012,
    FR-013).
    """
    document, reader = read_yaml(data, file)
    version = document.get("schema_version")
    if type(version) is int and version != supported:
        place = reader.values[("schema_version",)]
        raise _invalid(
            reader.problem(place, "schema_version", _version_message(version, supported, retired))
        )
    return validate(document, reader, Configuration)


def _version_message(version: int, supported: int, retired: Mapping[int, str]) -> str:
    if version > supported:
        return (
            f"schema version {version} was written for a newer opscout, which reads version "
            f"{supported} here; upgrade opscout"
        )
    if version in retired:
        return (
            f"schema version {version} is retired; follow its migration note at "
            f"{MIGRATION_NOTES}{retired[version]} to move to version {supported}"
        )
    return f"unknown schema version; this opscout reads version {supported}"
