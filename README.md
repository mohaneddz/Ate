![Ate](screenshots/cover.avif)

# <img src="screenshots/icon.webp" alt="Ate icon" width="42" height="42" align="top"> &nbsp;Ate

A small Windows CLI that reserves Webetu meals when your PC is online. Setup
requires a student account, without an APK or XAPK.

- Breakfast and dinner: your dorm, every day.
- Lunch: your chosen main restaurant, Sunday–Thursday.
- Existing bookings are checked first; conflicting bookings stop the run.
- Each submission is read back from the server before being called confirmed.
- Passwords stay in Windows DPAPI encrypted files under
  `%LOCALAPPDATA%\Ate\state` for both install methods. The fixed app signing
  constant is included in the client. Runtime session tokens stay in memory.
- Credentials, APKs, analysis output, and local logs are excluded from Git.

## Install

Needs **Windows 10 or 11, 64-bit** and internet access.

1. Download the release ZIP, extract the whole folder (keep the `scripts`
   subfolder beside `install.bat`), and double-click **`install.bat`** — no
   Python needed. Windows asks for administrator access to copy the app into
   `%ProgramFiles%\Ate\bin`. To install from a clone instead, install Python
   3.11+ and run `install.bat` from the repository folder.
2. Enter your student number and password (input is hidden), then pick your dorm
   and main restaurant from your account's live list and how many days to keep
   booked.
3. The installer saves your account encrypted for your Windows user, puts `res`
   on your PATH, registers the background checker, and opens a ready terminal.
   From there:

```cmd
res 3            :: keep the next 3 days booked, and book what is open now
res show         :: see your current and upcoming reservations
res help         :: list every command
```

That is the whole setup. The background task then keeps your horizon filled
whenever the PC is signed in and online.

If you open your own terminal and `res` is not recognized yet, sign out of
Windows and back in so Explorer picks up the updated PATH — or run
`%ProgramFiles%\Ate\bin\ate.exe` directly. Setup needs the Webetu services to be
reachable; if it cannot connect, no background task is installed, so just run
`install.bat` again once the service is back.

If `res` raises `ModuleNotFoundError: No module named 'reserve_cli'`, an older
editable Python installation may still point to a checkout that was moved or
deleted. From the current repository folder, repair the command with:

```cmd
python -m pip uninstall reserve-meals-cli
python -m pip install .
```

Current source installs copy the package into Python so moving the checkout
does not break the command.

> `res` and `ate` are the same command — use whichever you like. The underlying
> `reserve-meals` entry point stays available for lower-level account work.

## Commands

Open a terminal and run:

```cmd
res 3
res until 10-12
res show
res log 30
res plan
res doctor
```

`res 3` saves a rolling order for the next three days and tries it immediately.
The scheduler keeps that horizon filled whenever the PC is signed in and online.
`res until 10-12` saves a fixed end date and tries the available dates now. For
short dates, the CLI chooses the next future occurrence; use `2026-10-12` for an
explicit year. Booking is limited to tomorrow through three days ahead, so
later dates remain in the order until their window opens.

`res show` displays confirmed bookings from today onward. `res log 30` displays
reservations and local CLI activity from the last 30 calendar days; substitute
any number from 1 to 366. Both use a cached encrypted reservation snapshot if
the service is temporarily unavailable. These other commands are also useful:

```cmd
res today
res preview 10-05
res date 10-05
res sync
res pause
res resume
res depots
res help
```

`res date` submits missing meals for one date, `res preview` shows the date
without booking, and `res sync` rechecks the current standing order. Existing
bookings and uncertain attempts still receive the same duplicate protection.

After a password change or login problem, run `res auth` to validate and save
new details. It keeps your standing order and clears the automatic login block
only after a successful login. A bad password or unavailable service leaves
the previous account data in place.

To skip typing, import account fields from a file with `res auth info.env` or
`res auth credentials.md` (JSON also works):

```text
student=YOUR_STUDENT_NUMBER
password=YOUR_PASSWORD
dorm_id=YOUR_DORM_ID
main_id=YOUR_MAIN_RESTAURANT_ID
days=3
```

The restaurant IDs and `days` are optional; without IDs the command lists your
available restaurants and asks you to choose, and `days` is used only when no
standing order exists. A Markdown file may use `student: ...` / `password: ...`
lines or a two-column table. **Do not commit credential files** — `*.env` and
`credentials*` are already gitignored.

The Windows package installs `ate.exe` under `%ProgramFiles%\Ate\bin` and adds
that folder to your user PATH. A source install adds the `res`/`ate` entry
points to Python's Scripts directory. Both share `%LOCALAPPDATA%\Ate\state`.
Installing a new release replaces an older `%LOCALAPPDATA%\Ate\bin` installation
and keeps its encrypted account data in the same user state folder.

## Lower-level account management

The `reserve-meals` command (also `python -m reserve_cli`) exposes the raw
operations behind the friendly commands:

```powershell
# Read available restaurants and current reservations.
python -m reserve_cli depots
python -m reserve_cli status

# Preview a date, then submit its missing meals.
python -m reserve_cli reserve --date 2026-10-05
python -m reserve_cli reserve --date 2026-10-05 --apply

# Set an order that ends on this date (inclusive).
python -m reserve_cli order until 2026-10-12

# Or maintain a rolling horizon; this continues until paused/replaced.
python -m reserve_cli order days 3

python -m reserve_cli order show
python -m reserve_cli run --dry-run
python -m reserve_cli run
python -m reserve_cli order pause
python -m reserve_cli order resume
```

Saving a new order replaces the previous order. The original app exposes a
three-day booking window: dates beyond that are deferred until the window opens.
The runner starts with tomorrow and uses the `Africa/Algiers` calendar. Friday
and Saturday lunches are left out of the plan.

## Run whenever the PC is online

`install.bat` registers the background task for you. To (re)install it on its
own:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install-schedule.ps1
```

The `Ate` task checks at sign-in and every five minutes. Windows requires
a network connection before starting it. After a successful run it makes no more
API calls that day unless the order changes or you run `run --force`. Missed
checks are picked up when the PC is available again. Transient failures back off
from five minutes to one hour; authentication rejection suspends automatic
login attempts. The task runs while your Windows user is signed in, including
when the screen is locked. It does not wake a sleeping or powered-off PC.

The scheduler uses `pythonw.exe` when available to avoid opening terminal windows.
Results and errors go to `%LOCALAPPDATA%\Ate\state\runs.jsonl`. The `--state-dir PATH` option
goes before the command when using a different local data folder.

```powershell
Get-ScheduledTaskInfo -TaskName 'Ate'
Get-Content "$env:LOCALAPPDATA\Ate\state\runs.jsonl" -Tail 20
Disable-ScheduledTask -TaskName 'Ate'
```

## Uncertain requests and password changes

A lost response is not permission to retry a booking. The CLI leaves a pending
record and blocks another submission of that meal. Inspect the official app and
run `status`; if the reservation exists, the next run reconciles it. Only after
confirming that it is absent, unlock it explicitly:

```powershell
python -m reserve_cli clear-pending --date 2026-10-05 --meal breakfast --confirmed-absent
python -m reserve_cli credentials --file info.env
```

The second command updates the encrypted password after a password change and
clears authentication suspension. MFA login is not implemented. API changes may
require updating the client. This CLI does not cancel or replace existing meals.
Avoid submitting the same meal simultaneously from the phone; the client cannot
make a check and a write atomic across two devices.

## Uninstall

Run `uninstall.bat` from the release archive or from `%ProgramFiles%\Ate\bin`.
It removes the task, the executable, and the PATH entry while preserving your
encrypted account data. To remove that data too:

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%ProgramFiles%\Ate\bin\scripts\uninstall-package.ps1" -PurgeData
```

To update, extract a newer archive and run its `install.bat`; your encrypted
account and standing order stay in the same user data folder.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests use fake services. They never submit live reservations.

To build the standalone Windows ZIP, install PyInstaller and run
`scripts/build-release.ps1`. The package excludes local account data, APKs,
and analysis files.
