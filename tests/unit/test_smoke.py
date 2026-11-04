# SPDX-License-Identifier: Apache-2.0
"""Smoke tests: the package installs, imports, and its command line answers."""

import importlib

import pytest

from opscout import __version__
from opscout.entrypoints.cli import main


@pytest.mark.parametrize("layer", ["core", "services", "adapters", "entrypoints"])
def test_every_layer_imports_and_states_its_rule(layer: str) -> None:
    module = importlib.import_module(f"opscout.{layer}")

    assert "ADR-0011" in (module.__doc__ or "")


def test_version_flag_prints_the_installed_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"opscout {__version__}\n"


def test_no_arguments_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out.startswith("usage: opscout")
