# Ate

Ate keeps your Webetu meals booked while your Windows PC is signed in and online.
It books breakfast and dinner at your dorm and Sunday through Thursday lunch at
your chosen main restaurant. Existing reservations are checked before a request
is sent.

**Windows 10 or 11 (64-bit) only.** Linux is not supported: Ate uses Windows
encryption for account data and Windows Task Scheduler for automatic checks.

## Install

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
become available. It cannot run while the PC is asleep or powered off.

If `res` is not found in a newly opened terminal, sign out of Windows and back
in to refresh PATH. You can also run `%ProgramFiles%\Ate\bin\ate.exe` directly.

## Update or uninstall

To update, extract a newer ZIP and run its `install.bat`. Your account and order
are kept. To uninstall, run `uninstall.bat` from the ZIP or from
`%ProgramFiles%\Ate\bin`. This keeps your encrypted account data for a future
installation.

To remove the account data too, run this command instead:

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%ProgramFiles%\Ate\bin\scripts\uninstall-package.ps1" -PurgeData
```

## From source

On Windows with Python 3.11+, run `install.bat` from the repository folder.
This installs the Python command and the same background task. Developers can
run `python -m unittest discover -s tests -q` and build the standalone ZIP with
`scripts/build-release.ps1` (PyInstaller required).
