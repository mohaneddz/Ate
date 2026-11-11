"""Choose where booking runs: this machine's scheduler (local) and the always-on server (cloud).

The two switches are independent. With both on, both machines check and book; each one
looks at the live reservations before every write, so a meal is never booked twice.
"""
from __future__ import annotations

import base64
import re
import shutil
import subprocess
import sys

from .store import Store

TARGET_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*$")
REMOTE_COMMANDS = {"state": "ate config", "on": "ate resume", "off": "ate pause"}
TASK_SCRIPT = """
$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName 'Ate' -ErrorAction SilentlyContinue
if (-not $task) { exit 2 }
if ($task.Description -notlike 'Ate:*') { exit 3 }
{action}
"""


class WhereError(Exception):
    pass


def powershell(script: str) -> subprocess.CompletedProcess:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        return subprocess.run(["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
                              capture_output=True, text=True, errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WhereError(f"Could not reach the Windows task scheduler: {exc}") from exc


def local_state() -> bool | None:
    """True when this machine's scheduler is on, False when off, None when none is installed."""
    if sys.platform == "win32":
        result = powershell(TASK_SCRIPT.replace(
            "{action}", "if ($task.State -eq 'Disabled') { exit 10 } else { exit 11 }"))
        if result.returncode in (2, 3):
            return None
        if result.returncode in (10, 11):
            return result.returncode == 11
        raise WhereError("Could not read the Ate task state.")
    if sys.platform.startswith("linux"):
        try:
            result = subprocess.run(["systemctl", "--user", "is-enabled", "ate.timer"],
                                    capture_output=True, text=True, errors="replace", timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = result.stdout.strip()
        return True if text == "enabled" else False if text == "disabled" else None
    return None


def set_local(enabled: bool) -> None:
    if local_state() is None:
        raise WhereError("No Ate scheduler is installed on this machine, so there is nothing to switch.")
    if sys.platform == "win32":
        verb = "Enable" if enabled else "Disable"
        result = powershell(TASK_SCRIPT.replace("{action}", f"{verb}-ScheduledTask -TaskName 'Ate' | Out-Null"))
        if result.returncode:
            raise WhereError("Windows did not change the Ate task: " + (result.stderr.strip() or "unknown error"))
        return
    action = "enable" if enabled else "disable"
    result = subprocess.run(["systemctl", "--user", action, "--now", "ate.timer"],
                            capture_output=True, text=True, errors="replace", timeout=30)
    if result.returncode:
        raise WhereError("systemd did not change the timer: " + result.stderr.strip())


def cloud_target(store: Store) -> dict | None:
    return (store.read("config", {}) or {}).get("cloud")


def save_cloud(store: Store, target: str, port: int) -> None:
    if not TARGET_PATTERN.match(target):
        raise WhereError("Use user@host, for example root@203.0.113.5 or deploy@box.example.com.")
    if not 1 <= port <= 65535:
        raise WhereError("The port must be from 1 to 65535.")
    with store.lock():
        settings = store.read("config", {}) or {}
        settings["cloud"] = {"target": target, "port": port}
        store.write("config", settings)


def remote(store: Store, action: str) -> str:
    target = cloud_target(store)
    if not target:
        raise WhereError("No server is saved yet. Run: cloud setup user@host [port]")
    if not shutil.which("ssh"):
        raise WhereError("The ssh command is not installed on this machine.")
    command = ["ssh", "-p", str(target["port"]), "-o", "ConnectTimeout=15", "--", target["target"],
               REMOTE_COMMANDS[action]]
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=90)
    except subprocess.TimeoutExpired:
        raise WhereError("The server did not answer in time.") from None
    if result.returncode:
        lines = result.stderr.strip().splitlines()
        detail = f" ({lines[-1]})" if lines else ""
        raise WhereError("Could not run the command on the server" + detail + ". "
                         "If your key has a passphrase, load it first with ssh-add.")
    return result.stdout


def cloud_state(store: Store) -> bool | None:
    """True when the server's standing order is active, False when paused, None when unknown."""
    text = remote(store, "state")
    if "PAUSED" in text:
        return False
    return True if "ACTIVE" in text else None


def set_cloud(store: Store, enabled: bool) -> bool | None:
    remote(store, "on" if enabled else "off")
    return cloud_state(store)
