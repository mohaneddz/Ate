"""Use one stable per-user data location for source and packaged commands."""
import os
from pathlib import Path
import sys


def default_state_dir() -> Path:
    if os.name == "nt" or getattr(sys, "frozen", False):
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            local = str(Path.home() / "AppData" / "Local")
        return Path(local) / "Ate" / "state"
    return Path(__file__).resolve().parents[1] / ".reserve"
