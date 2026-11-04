# SPDX-License-Identifier: Apache-2.0
# Developer tasks. Run them through uv, so every tool comes from uv.lock (ADR-0020):
#
#     uv run just <recipe>

# List the recipes.
default:
    @just --list

# Format the code and apply safe lint fixes.
fmt:
    ruff format .
    ruff check --fix .

# Check formatting and lint, without changing files.
lint:
    ruff format --check .
    ruff check .

# Type-check with mypy --strict.
types:
    mypy

# Check the import contracts between layers (ADR-0011, ADR-0021).
imports:
    lint-imports

# Run the test suite; extra arguments go to pytest.
test *args:
    pytest {{ args }}

# Validate the marketplace and plugin manifests (ADR-0003). Needs Claude Code (ADR-0020).
plugin:
    claude plugin validate --strict .
    claude plugin validate --strict plugins/opscout

# Run every local gate that exists so far.
check: lint types imports test plugin
