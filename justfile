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

# The coverage gate on core and services (ADR-0016).
coverage:
    coverage run -m pytest -q
    coverage report

# The fast checks, which the Stop hook runs before the agent stops (ADR-0018).
fast: lint types imports test

# Install the git hooks and build their tools. gitleaks and actionlint are built with Go,
# which pre-commit downloads the first time if it is missing (ADR-0020).
setup:
    pre-commit install --install-hooks

# Run the pre-commit stage of the gates on every file (ADR-0016). The commit-msg and
# pre-push stages run when you commit and when you push.
check:
    pre-commit run --all-files
