# SPDX-License-Identifier: Apache-2.0
"""Claude Code hooks for working on this repository (ADR-0018).

``.claude/settings.json`` runs each one through uv, in exec form and from the project
directory, as ``python -m tools.hooks.<name>`` (ADR-0021).
"""
