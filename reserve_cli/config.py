"""User settings and the installed background timer."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

from .store import Store, StoreError

DEFAULT_MINUTES = 5
MAX_MINUTES = 7 * 24 * 60


def parse_interval(value: str) -> int:
    match = re.fullmatch(r"([1-9]\d*)\s*(m|min|minutes?|h|hours?|d|days?)", value.strip().lower())
    if not match:
        raise ValueError("Use a whole number followed by m, h, or d, for example 15m, 2h, or 1d.")
    multiplier = 1 if match[2].startswith("m") else 60 if match[2].startswith("h") else 1440
    minutes = int(match[1]) * multiplier
    if minutes > MAX_MINUTES:
        raise ValueError("Choose an interval from 1 minute through 7 days.")
    return minutes


def interval_minutes(store: Store) -> int:
    minutes = store.read("config", {}).get("interval_minutes", DEFAULT_MINUTES)
    if type(minutes) is not int or not 1 <= minutes <= MAX_MINUTES:
        raise StoreError("The saved check interval is invalid.")
    return minutes


def interval_label(minutes: int) -> str:
    if minutes % 1440 == 0:
        return f"{minutes // 1440} day(s)"
    if minutes % 60 == 0:
        return f"{minutes // 60} hour(s)"
    return f"{minutes} minute(s)"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StoreError(f"Could not update the background timer: {exc}") from exc
    if result.returncode:
        raise StoreError("Could not update the background timer: " + (result.stderr.strip() or result.stdout.strip()))
    return result


def apply_interval(store: Store, minutes: int) -> bool:
    """Update an existing scheduler. Return false when no installer has set one up."""
    if sys.platform == "win32":
        # A numeric argument is the only value inserted into this fixed script.
        script = f"""
$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName 'Ate' -ErrorAction SilentlyContinue
if (-not $task) {{ exit 2 }}
if ($task.Description -notlike 'Ate:*') {{ throw 'The Ate task belongs to another application.' }}
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$triggers = @(
  (New-ScheduledTaskTrigger -AtLogOn -User $user),
  (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes {minutes}))
)
Set-ScheduledTask -TaskName 'Ate' -Trigger $triggers | Out-Null
"""
        import base64
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
                                capture_output=True, text=True, errors="replace", timeout=30)
        if result.returncode == 2:
            return False
        if result.returncode:
            raise StoreError("Could not update the background timer: " + (result.stderr.strip() or result.stdout.strip()))
        return True
    if sys.platform.startswith("linux"):
        config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        unit = config_home / "systemd" / "user" / "ate.timer"
        if not unit.exists():
            return False
        current = unit.read_text(encoding="utf-8")
        if "Unit=ate.service" not in current or "OnUnitInactiveSec=" not in current:
            raise StoreError("The installed Ate timer has an unexpected format.")
        updated = re.sub(r"(?m)^OnUnitInactiveSec=.*$", f"OnUnitInactiveSec={minutes}min", current)
        unit.write_text(updated, encoding="utf-8")
        try:
            _run(["systemctl", "--user", "daemon-reload"])
            _run(["systemctl", "--user", "restart", "ate.timer"])
        except BaseException:
            unit.write_text(current, encoding="utf-8")
            _run(["systemctl", "--user", "daemon-reload"])
            raise
        return True
    raise StoreError("Background checks require Windows or Linux.")


def set_interval(store: Store, minutes: int) -> bool:
    with store.lock():
        old = interval_minutes(store)
        installed = apply_interval(store, minutes)
        try:
            settings = store.read("config", {})
            settings["interval_minutes"] = minutes
            store.write("config", settings)
        except BaseException:
            if installed:
                apply_interval(store, old)
            raise
        return installed
