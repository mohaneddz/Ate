![Ate](screenshots/cover.avif)

# Ate

Ate keeps your Webetu meals booked while your PC is signed in and online.
It books breakfast and dinner at your dorm and Sunday through Thursday lunch at
your chosen main restaurant. Existing reservations are checked before a request
is sent.

Available for Windows 10/11 (64-bit) and Linux with a systemd user session.

## Install on Windows

1. Download the Windows ZIP from the [latest release](https://github.com/mohaneddz/Ate/releases/latest)
   and extract the whole folder.
2. Double-click **`install.bat`** and approve the Windows administrator prompt.
   Python is not needed.
3. Enter your student number and password, choose your dorm and main restaurant,
   and choose how many days to keep booked.

The installer puts the app in `%ProgramFiles%\Ate\bin`, adds `res` to your PATH,
and starts a background check at sign-in and every five minutes while online.
Your account data is encrypted for your Windows user in
`%LOCALAPPDATA%\Ate\state`.

## Install on Linux

Requires Python 3.11+, `venv`, a running systemd user session, and internet
access. Download `Ate-0.7.0-linux.tar.gz` from the
[latest release](https://github.com/mohaneddz/Ate/releases/latest), then run:

```sh
tar -xzf Ate-0.7.0-linux.tar.gz
cd Ate-0.7.0-linux
./install.sh
```

The installer asks for your account details and enables a user timer. It puts
`res` in `~/.local/bin` and the app in `~/.local/share/ate`. Account data lives
in `~/.local/state/ate` (or under `XDG_STATE_HOME`). Linux protects these files with
user-only permissions (0700 directory, 0600 files); unlike Windows, they are
not encrypted. Do not run the installer with `sudo`.

## Use

Open a terminal and run:

| Command | What it does |
| --- | --- |
| `res 3` | Keep the next three days booked. |
| `res until 10-12` | Keep booking through October 12. |
| `res show` | Show current and upcoming reservations. |
| `res log 30` | Show reservations and activity from the last 30 days. |
| `res plan` | Preview the standing order. |
| `res pause` / `res resume` | Stop or restart automatic booking. |
| `res auth` | Update your account details or password. |
| `res help` | Show every command. |

Webetu opens bookings only a few days ahead. Ate checks again as later dates
become available. It cannot run while the PC is asleep or powered off. If you
cancel `res auth` with Ctrl+C, the previous account and order are restored.

On Windows, if `res` is not found in a newly opened terminal, sign out and back
in to refresh PATH. You can also run `%ProgramFiles%\Ate\bin\ate.exe` directly.
On Linux, add `~/.local/bin` to PATH if needed.

## Screenshots

| | |
| --- | --- |
| ![res show](screenshots/show.avif) | ![res log](screenshots/log.avif) |
| `res show` — current and upcoming reservations | `res log` — reservations and activity |
| ![res auth](screenshots/auth.avif) | ![res help](screenshots/help.avif) |
| `res auth` — update account details | `res help` — every command |

## Update or uninstall

On Windows, extract a newer ZIP and run its `install.bat` to update. To
uninstall, run `uninstall.bat` from the ZIP or `%ProgramFiles%\Ate\bin`.
Account data is kept for a future installation. To remove it too, run:

To remove the account data too, run this command instead:

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%ProgramFiles%\Ate\bin\scripts\uninstall-package.ps1" -PurgeData
```

On Linux, run `./install.sh` from a newer archive to update. Run
`~/.local/share/ate/uninstall.sh` to uninstall while keeping account data, or
add `--purge-data` to remove it too.

## From source

On Windows with Python 3.11+, run `install.bat` from the repository folder.
Developers can run `python -m unittest discover -s tests -q`, build the Windows
ZIP with `scripts/build-release.ps1` (PyInstaller required), and build the Linux
archive with `python scripts/build-linux-release.py`.
