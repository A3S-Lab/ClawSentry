"""Minimal .env.clawsentry auto-loader (stdlib only, no dependencies).

Loaded at startup by gateway and stack to avoid requiring manual
``source .env.clawsentry``. Does NOT override existing environment variables.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_FILE_NAME = ".env.clawsentry"


def load_dotenv(search_dir: Path | None = None) -> int:
    """Load .env.clawsentry from *search_dir* (default: cwd).

    Returns the number of variables loaded.
    Does not override existing environment variables.
    """
    base = search_dir or Path.cwd()
    env_file = base / ENV_FILE_NAME

    if not env_file.is_file():
        return 0

    loaded = 0
    try:
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip surrounding quotes
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
                loaded += 1
    except OSError:
        logger.warning("Could not read %s", env_file)

    if loaded:
        logger.info("Loaded %d env vars from %s", loaded, env_file)

    return loaded
