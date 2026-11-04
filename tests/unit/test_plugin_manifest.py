# SPDX-License-Identifier: Apache-2.0
"""The plugin and the Python package are released in lockstep (ADR-0016)."""

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_MANIFEST = REPO_ROOT / "plugins" / "opscout" / ".claude-plugin" / "plugin.json"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def test_the_plugin_and_the_package_share_one_version() -> None:
    plugin = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    assert plugin["version"] == project["version"]
