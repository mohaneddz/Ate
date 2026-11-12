"""Find a newer GitHub release and install it in place.

Linux replaces its own executable. Windows lives in Program Files, so it asks the
elevated AteUpdate task (registered by the installer) to do the swap. Both download
only from this project's release page and check the published SHA-256 first.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import time

import requests

from .chatformat import updated_alert
from .store import Store
from .version import __version__

REPO = "mohaneddz/Ate"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_URL = f"https://github.com/{REPO}/releases/download"
CHECK_EVERY = timedelta(hours=24)
MAX_DOWNLOAD = 300 * 1024 * 1024
TAG_PATTERN = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
UPDATE_TASK = "AteUpdate"
WINDOWS_WAIT_SECONDS = 180


def on_windows() -> bool:
    return sys.platform == "win32"


def on_linux() -> bool:
    return sys.platform.startswith("linux")


class UpdateError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    tag: str


def parse_version(text: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", text.strip())
    if not match:
        raise UpdateError(f"Unrecognised version: {text!r}.")
    return tuple(int(part) for part in match.groups())


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def latest_release() -> Release:
    try:
        response = requests.get(LATEST_URL, timeout=15, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "ate-updater"})
        response.raise_for_status()
        tag = str(response.json().get("tag_name", ""))
    except (requests.RequestException, ValueError) as exc:
        raise UpdateError("Could not reach the release page.") from exc
    if not TAG_PATTERN.fullmatch(tag):
        raise UpdateError("The latest release has an unexpected tag.")
    return Release(tag.removeprefix("v"), tag)


def archive_name(version: str) -> str:
    return f"Ate-{version}-linux.tar.gz" if on_linux() else f"Ate-{version}-win64.zip"


def download(url: str, target: Path) -> None:
    try:
        with requests.get(url, stream=True, timeout=30, headers={"User-Agent": "ate-updater"}) as response:
            response.raise_for_status()
            size = 0
            with target.open("wb") as stream:
                for chunk in response.iter_content(1 << 16):
                    size += len(chunk)
                    if size > MAX_DOWNLOAD:
                        raise UpdateError("The download is larger than expected.")
                    stream.write(chunk)
    except requests.RequestException as exc:
        raise UpdateError("The download failed.") from exc


def published_digest(release: Release) -> str:
    name = archive_name(release.version)
    try:
        response = requests.get(f"{DOWNLOAD_URL}/{release.tag}/{name}.sha256", timeout=15,
                                headers={"User-Agent": "ate-updater"})
        response.raise_for_status()
    except requests.RequestException as exc:
        raise UpdateError("The release has no checksum file.") from exc
    match = re.match(r"([0-9a-fA-F]{64})\s+\*?(\S+)", response.text)
    if not match or match.group(2) != name:
        raise UpdateError("The checksum file does not match the release archive.")
    return match.group(1).lower()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def linux_app_dir() -> Path | None:
    """The folder install.sh uses, but only when this process is the executable installed there."""
    if not (on_linux() and getattr(sys, "frozen", False)):
        return None
    executable = Path(sys.executable).resolve()
    expected = (Path.home() / ".local" / "share" / "ate").resolve()
    return executable.parent if executable.parent == expected and executable.name == "ate" else None


def windows_install_root() -> Path | None:
    if not (on_windows() and getattr(sys, "frozen", False)):
        return None
    executable = Path(sys.executable).resolve()
    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files")).resolve()
    root = executable.parent.parent
    return root if root == program_files / "Ate" and executable.parent.name == "bin" else None


def windows_task_ready() -> bool:
    try:
        result = subprocess.run(["schtasks", "/Query", "/TN", UPDATE_TASK], capture_output=True,
                                text=True, errors="replace", timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def blocker() -> str | None:
    """Why this copy cannot update itself, or None when it can."""
    if on_linux():
        if linux_app_dir() is None:
            return "This copy was not installed by the Ate installer, so update it the way you installed it."
        return None
    if on_windows():
        if windows_install_root() is None:
            return "This copy was not installed by the Ate installer, so update it the way you installed it."
        if not windows_task_ready():
            return "This install predates automatic updates. Download the latest ZIP once and run install.bat."
        return None
    return "Updates are available on Windows and Linux only."


def install_linux(release: Release, app_dir: Path) -> None:
    name = archive_name(release.version)
    member = f"Ate-{release.version}-linux/ate"
    with tempfile.TemporaryDirectory(dir=app_dir, prefix=".update-") as work:
        archive = Path(work) / name
        download(f"{DOWNLOAD_URL}/{release.tag}/{name}", archive)
        if file_digest(archive) != published_digest(release):
            raise UpdateError("The download does not match its published checksum; nothing was changed.")
        staged = Path(work) / "ate"
        try:
            with tarfile.open(archive, "r:gz") as bundle:
                info = bundle.getmember(member)
                if not info.isfile() or info.size > MAX_DOWNLOAD:
                    raise UpdateError("The archive does not contain a usable program.")
                source = bundle.extractfile(info)
                with staged.open("wb") as stream:
                    stream.write(source.read())
        except (KeyError, tarfile.TarError, OSError) as exc:
            raise UpdateError("The archive could not be read.") from exc
        staged.chmod(0o700)
        try:
            check = subprocess.run([str(staged), "version"], capture_output=True, text=True,
                                   errors="replace", timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError("The new program did not start; nothing was changed.") from exc
        if check.returncode or release.version not in check.stdout:
            raise UpdateError("The new program did not report the expected version; nothing was changed.")
        os.replace(staged, app_dir / "ate")


def install_windows() -> str:
    """Run the elevated update task and wait for it to report. Returns the new version."""
    root = windows_install_root()
    status_file = root / "update-status.txt"
    started = time.time()
    try:
        result = subprocess.run(["schtasks", "/Run", "/TN", UPDATE_TASK], capture_output=True,
                                text=True, errors="replace", timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError("Could not start the update task.") from exc
    if result.returncode:
        raise UpdateError("Could not start the update task.")
    deadline = started + WINDOWS_WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(2)
        try:
            if status_file.stat().st_mtime < started - 1:
                continue
            text = status_file.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text.startswith("ok "):
            return text[3:].strip()
        if text.startswith("error "):
            raise UpdateError(text[6:].strip() or "The update failed.")
    raise UpdateError("The update did not finish in time. It may still complete in the background.")


def start_windows_update() -> None:
    """Fire the update task without waiting; the next scheduled run reports the result."""
    try:
        subprocess.run(["schtasks", "/Run", "/TN", UPDATE_TASK], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        pass


def apply(release: Release) -> str:
    """Install the release on this machine and return the version now on disk."""
    reason = blocker()
    if reason:
        raise UpdateError(reason)
    if on_windows():
        return install_windows()
    install_linux(release, linux_app_dir())
    return release.version


def autoupdate_enabled(store: Store) -> bool:
    return store.read("config", {}).get("autoupdate", True) is not False


def set_autoupdate(store: Store, enabled: bool) -> None:
    with store.lock():
        settings = store.read("config", {})
        settings["autoupdate"] = enabled
        store.write("config", settings)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def background(store: Store) -> tuple[list[str], list[str]]:
    """Called after each scheduled run. Returns (log lines, Telegram alerts); never raises."""
    logs: list[str] = []
    alerts: list[str] = []
    try:
        with store.lock():
            state = store.read("update", {})
            previous = state.get("running_version")
            if previous != __version__:
                state["running_version"] = __version__
                if previous:
                    logs.append(f"Ate updated from {previous} to {__version__}.")
                    alerts.append(updated_alert(previous, __version__))
            checked = state.get("checked_at")
            due = not checked or _now() - datetime.fromisoformat(checked) >= CHECK_EVERY
            if autoupdate_enabled(store) and due and blocker() is None:
                # Stamp first so a failing check is retried tomorrow, not on every run.
                state["checked_at"] = _now().isoformat()
                store.write("update", state)
                release = latest_release()
                state["latest"] = release.version
                if is_newer(release.version):
                    if on_windows():
                        start_windows_update()
                        logs.append(f"Updating Ate from {__version__} to {release.version}.")
                    else:
                        apply(release)
                        logs.append(f"Ate {release.version} is installed and starts with the next run.")
            store.write("update", state)
    except (UpdateError, ValueError, OSError) as exc:
        logs.append(f"Automatic update did not finish: {exc}")
    except Exception as exc:
        logs.append(f"Automatic update did not finish: {type(exc).__name__}")
    return logs, alerts
