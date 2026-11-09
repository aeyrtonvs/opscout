# SPDX-License-Identifier: Apache-2.0
"""The triage reference names what a user needs (spec 012, FR-026; T046)."""

from pathlib import Path

import pytest

from opscout.core.config import Triage

REPO_ROOT = Path(__file__).resolve().parents[3]
TRIAGE = REPO_ROOT / "docs" / "reference" / "triage.md"
TOOLS = REPO_ROOT / "docs" / "reference" / "tools.md"
CONFIGURATION = REPO_ROOT / "docs" / "reference" / "configuration.md"
NEW_TOOLS = (
    "begin_triage",
    "check_verdict",
    "record_agreement",
    "show_evidence",
    "search_iac",
    "read_iac",
)


def spec(requirement: str) -> pytest.MarkDecorator:
    """Mark a test as proving one requirement of spec 012."""
    return pytest.mark.spec("012", requirement)


@spec("FR-026")
def test_the_reference_names_the_tools_keys_commands_and_server_name() -> None:
    triage = TRIAGE.read_text(encoding="utf-8")
    tools = TOOLS.read_text(encoding="utf-8")
    configuration = CONFIGURATION.read_text(encoding="utf-8")
    for tool in NEW_TOOLS:
        assert f"| `{tool}` |" in tools, tool
    for key in Triage.model_fields:
        assert f"`{key}`" in configuration, key
        assert key in triage, key
    assert "opscout triage runs" in triage
    assert "opscout triage show" in triage
    assert "**`observability`**" in triage
    assert "`include_background`" in tools
    assert "| `evidence` |" in tools
