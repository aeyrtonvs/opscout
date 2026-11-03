# SPDX-License-Identifier: Apache-2.0
"""Smoke tests: the package installs, imports, and its command line answers."""

import pytest

from opscout import __version__
from opscout.entrypoints.cli import main


def test_version_flag_prints_the_installed_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"opscout {__version__}\n"


def test_no_arguments_prints_help_and_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out.startswith("usage: opscout")
