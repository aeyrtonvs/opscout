# SPDX-License-Identifier: Apache-2.0
"""Scaffold for this case (spec 004): see ../_scaffold/scratch_repository.py."""

import runpy
from pathlib import Path

shared = Path(__file__).resolve().parents[1] / "_scaffold" / "scratch_repository.py"
runpy.run_path(str(shared))["make"](branch="main")
