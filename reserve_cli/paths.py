"""Use one stable per-user data location for source and packaged commands."""
import os
from pathlib import Path
import sys


def default_state_dir() -> Path:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if not local:
            local = str(Path.home() / "AppData" / "Local")
        return Path(local) / "Ate" / "state"
    if sys.platform.startswith("linux"):
        state_home = os.environ.get("XDG_STATE_HOME", "")
        root = Path(state_home) if state_home and Path(state_home).is_absolute() else Path.home() / ".local" / "state"
        return root / "ate"
    raise RuntimeError("Ate supports Windows and Linux only.")
