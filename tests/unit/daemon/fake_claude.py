#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""A stand-in for the ``claude`` executable that prints recorded streams (spec 007).

Tests copy this file into a temporary directory as ``claude`` and write ``claude.json``
beside it. The runner gives its child only an allow-listed environment, so the fake reads
its settings from that file, not from environment variables:

- ``log``: a file to which each start appends one JSON line with its arguments, standard
  input, environment and working directory;
- ``streams``: one recorded stream per attempt; the last one repeats;
- ``exit``: the exit status (default 0);
- ``pause``: seconds to wait after the first line, to prove the runner stops a child whose
  start-up report it refuses.
"""

import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    """Record this start, print its stream, and exit with the configured status."""
    settings = json.loads(Path(sys.argv[0]).with_suffix(".json").read_text(encoding="utf-8"))
    log = Path(settings["log"])
    attempt = len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0
    start = {
        "argv": sys.argv[1:],
        "stdin": sys.stdin.read(),
        "env": dict(os.environ),
        "cwd": str(Path.cwd()),
    }
    with log.open("a", encoding="utf-8") as file:
        file.write(json.dumps(start) + "\n")
    streams = settings["streams"]
    stream = Path(streams[min(attempt, len(streams) - 1)])
    for number, line in enumerate(stream.read_text(encoding="utf-8").splitlines()):
        try:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        except BrokenPipeError:
            return 1
        if number == 0 and settings.get("pause"):
            time.sleep(float(settings["pause"]))
    return int(settings.get("exit", 0))


if __name__ == "__main__":
    sys.exit(main())
