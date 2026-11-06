# SPDX-License-Identifier: Apache-2.0
"""The tools reference matches the code (spec 011, FR-028)."""

import re
from pathlib import Path

import pytest

from opscout.core.aws import RESOURCE_TYPES
from opscout.core.tools import CAP_CEILINGS, CAP_DEFAULTS, ErrorReason
from opscout.services.tools.registry import REGISTRY

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "reference" / "tools.md"
CONFIGURATION = REPO_ROOT / "docs" / "reference" / "configuration.md"


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 011."""
    return pytest.mark.spec("011", requirement)


@spec("FR-028")
def test_every_tool_error_type_and_cap_is_documented() -> None:
    text = DOC.read_text(encoding="utf-8")

    for tool in REGISTRY:
        assert f"| `{tool.name}` |" in text, tool.name
    for reason in ErrorReason:
        assert f"| `{reason.value}` |" in text, reason.value
    for kind in RESOURCE_TYPES:
        assert f"`{kind}`" in text, kind
    for name, ceiling in CAP_CEILINGS.items():
        row = re.search(rf"^\| `{name}` \| ([\d,]+) \| ([\d,]+) \|$", text, re.MULTILINE)
        assert row is not None, name
        assert int(row[1].replace(",", "")) == CAP_DEFAULTS[name], name
        assert int(row[2].replace(",", "")) == ceiling, name


@spec("FR-028")
def test_the_configuration_reference_has_the_three_sections() -> None:
    text = CONFIGURATION.read_text(encoding="utf-8")

    for section in ("alerts", "aws", "tools"):
        assert f"### `{section}` (optional; spec 011)" in text, section
    assert "[tools.md](tools.md)" in text
