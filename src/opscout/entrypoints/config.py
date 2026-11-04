# SPDX-License-Identifier: Apache-2.0
"""Load the configuration from its directory (spec 002, FR-032).

Every part of the engine that needs the configuration calls ``load_config``; nothing else
reads ``config.yaml``. Only that file is read: the rest of the directory, such as the leak
check's private deny-list, is never opened.
"""

from pathlib import Path

from opscout.core.config import ConfigLocationError, Configuration
from opscout.services.config import CONFIG_FILE, MAX_BYTES, parse_config


def config_file(directory: Path) -> Path:
    """Return the path of the configuration file in a directory."""
    return directory / CONFIG_FILE


def load_config(directory: Path) -> Configuration:
    """Read and validate ``config.yaml`` in ``directory``.

    Raises ``ConfigLocationError`` when the directory or the file is missing or unreadable,
    and ``InvalidConfigError`` with every problem when the file is invalid.
    """
    if not directory.exists():
        raise ConfigLocationError(f"{directory}: no such directory")
    if not directory.is_dir():
        raise ConfigLocationError(f"{directory}: not a directory")
    path = config_file(directory)
    if not path.is_file():
        hint = ""
        if (directory / "config.yml").exists():
            hint = "; found config.yml: rename it to config.yaml"
        raise ConfigLocationError(f"{path}: no such file{hint}")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
    except OSError as error:
        raise ConfigLocationError(f"{path}: cannot be read ({error.strerror})") from None
    return parse_config(data, str(path))
