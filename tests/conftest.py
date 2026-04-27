"""Shared test fixtures and configuration."""

import os
from pathlib import Path

# Set defaults for environment variables before any bird_interact_agents imports
_DEFAULTS = {
    "BIRD_BIRD_INTERACT_ROOT": str(Path.home() / "Dropbox/SLayer/BIRD-Interact"),
    "BIRD_DATA_PATH": str(Path.home() / "Dropbox/SLayer/mini-interact/mini_interact.jsonl"),
    "BIRD_DB_PATH": str(Path.home() / "Dropbox/SLayer/mini-interact"),
}
for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)
