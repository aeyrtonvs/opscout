# SPDX-License-Identifier: Apache-2.0
"""The configuration contract, schema version 1 (spec 002, ADR-0014).

The models here are the source of truth: the loader enforces them, and the JSON Schema
committed at ``schemas/config.schema.json`` is generated from them. Version 1 holds only
``schema_version``; each later feature adds its section as an additive change.

Rules for every later section:

- An additive change (a new optional key or section) keeps ``SCHEMA_VERSION``. A breaking
  change (removing, renaming or retyping a key, or making one required) raises it, moves
  the old version to ``RETIRED_VERSIONS`` and adds a migration note to
  ``docs/reference/configuration.md``.
- No key accepts a secret value. A credential is named by a ``KeychainRef``.
- Every field has a description, which editors show.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints
from pydantic_core import PydanticCustomError

SCHEMA_VERSION: Final = 1
"""The only major version of the schema this engine reads."""

RETIRED_VERSIONS: Final[Mapping[int, str]] = MappingProxyType({})
"""Each retired major version, mapped to the anchor of its migration note."""

MIGRATION_NOTES: Final = "docs/reference/configuration.md"
SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID: Final = (
    "https://raw.githubusercontent.com/aeyrtonvs/opscout/main/schemas/config.schema.json"
)

_KeychainName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[^\s\x00-\x1f\x7f]+$"),
]


def _exact_int(value: object) -> object:
    """Refuse anything but an integer: a literal alone would accept ``1.0`` and ``True``."""
    if type(value) is not int:
        raise PydanticCustomError("int_type", "Input should be a valid integer")
    return value


class KeychainRef(BaseModel):
    """A credential in the OS keychain, named by its service and account, never by its value."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    service: _KeychainName = Field(
        description="The keychain service under which the credential is stored.",
    )
    account: _KeychainName | None = Field(
        default=None,
        description="The keychain account of the credential, when the service holds several.",
    )


class Configuration(BaseModel):
    """The private opscout configuration (config.yaml in the configuration directory)."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        title="opscout configuration",
    )

    schema_version: Annotated[Literal[1], BeforeValidator(_exact_int)] = Field(
        description=(
            "The major version of the configuration schema this file follows. "
            "This engine reads version 1."
        ),
    )


@dataclass(frozen=True, order=True)
class Problem:
    """One thing wrong with a configuration file. It never holds the value found."""

    file: str
    line: int
    column: int
    path: str = field(compare=False)
    message: str = field(compare=False)

    def render(self) -> str:
        """Return the problem as ``file:line:column: path: message``."""
        return f"{self.file}:{self.line}:{self.column}: {self.path}: {self.message}"


class ConfigError(Exception):
    """The configuration cannot be used."""


class ConfigLocationError(ConfigError):
    """The configuration directory or file is missing or cannot be read."""


class InvalidConfigError(ConfigError):
    """The configuration file has problems."""

    def __init__(self, problems: tuple[Problem, ...]) -> None:
        super().__init__(f"{len(problems)} problem(s) in the configuration")
        self.problems = problems


def schema_document() -> dict[str, Any]:
    """Return the JSON Schema of the configuration."""
    return {"$schema": SCHEMA_DIALECT, "$id": SCHEMA_ID, **Configuration.model_json_schema()}


def schema_text() -> str:
    """Return the JSON Schema as committed at ``schemas/config.schema.json``."""
    return json.dumps(schema_document(), indent=2, ensure_ascii=False) + "\n"
