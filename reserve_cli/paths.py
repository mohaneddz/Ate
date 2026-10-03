"""Use a stable per-user data location in a packaged executable."""
import os
from pathlib import Path
import sys


def default_state_dir() -> Path:
    if getattr(sys, "frozen", False):
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            local = str(Path.home() / "AppData" / "Local")
        return Path(local) / "CouscousCron" / "state"
    return Path(__file__).resolve().parents[1] / ".reserve"
