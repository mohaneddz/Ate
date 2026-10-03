# Ate 🍽️

A small Windows CLI that reserves Webetu meals when your PC is online. Setup
requires a student account, without an APK or XAPK.

For a Windows install without Python, download the release ZIP, extract it and
run `install.cmd`. To install from a clone, install Python 3.11+ and run
`install.cmd` from the repository. The [install guide](INSTALL.md) covers both
paths, authentication, automatic startup, updates, and removal.

- Breakfast and dinner: your dorm, every day.
- Lunch: your chosen main restaurant, Sunday–Thursday.
- Existing bookings are checked first; conflicting bookings stop the run.
- Each submission is read back from the server before being called confirmed.
- Passwords stay in Windows DPAPI encrypted files under
  `%LOCALAPPDATA%\Ate\state` for both install methods. The fixed app signing
  constant is included in the client. Runtime session tokens stay in memory.
- Credentials, APKs, analysis output, and local logs are excluded from Git.

## Setup

From a clone on Windows, under the Windows user who will run the schedule:

```powershell
git clone https://github.com/mohaneddz/ate.git
cd ate
.\install.cmd
```

The installer installs the Python package, runs the `res auth` flow, then registers
the background task. `res auth` asks for your student number, hidden password,
and dorm/main restaurants from your account's live list. Use
`res auth info.env` or `res auth credentials.md` to import account fields from a
file. Optional `dorm_id`, `main_id`, and `days` fields make first setup
noninteractive. See the [install guide](INSTALL.md) for formats and examples.
Do not commit credential files.

## Use it

The Windows package installs `ate.exe` under `%LOCALAPPDATA%\Ate\bin` and adds
it to your user PATH. A source install adds the `ate` entry point to Python's
Scripts directory. Open a **new Command Prompt** and use:

```cmd
ate 3
ate until 10-12
ate show
ate log 30
ate plan
ate doctor
```

`ate 3` saves a rolling order for the next three days and tries it immediately.
The scheduler keeps that horizon filled whenever the PC is signed in and online.
`ate until 10-12` saves a fixed end date and tries the available dates now. For
short dates, the CLI chooses the next future occurrence; use `2026-10-12` for an
explicit year. Booking is limited to tomorrow through three days ahead, so
later dates remain in the order until their window opens.

`ate show` displays confirmed bookings from today onward. `ate log 30` displays
reservations and local CLI activity from the last 30 calendar days; substitute
any number from 1 to 366. Both use a cached encrypted reservation snapshot if
the service is temporarily unavailable. These other commands are also useful:

```cmd
ate today
ate preview 10-05
ate date 10-05
ate sync
ate pause
ate resume
ate depots
ate help
```

`ate date` submits missing meals for one date, `ate preview` shows the date
without booking, and `ate sync` rechecks the current standing order. Existing
bookings and uncertain attempts still receive the same duplicate protection.
The old `res` command remains an alias in source and packaged installs.

After a password change or login problem, run `ate auth` to validate and save
new details. It keeps your standing order and clears the automatic login block
only after a successful login. A bad password or unavailable service leaves
the previous account data in place.

The underlying `reserve-meals` command remains available for setup and more
specific account management:

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

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests use fake services. They never submit live reservations.

To build the standalone Windows ZIP, install PyInstaller and run
`scripts/build-release.ps1`. The package excludes local account data, APKs,
and analysis files.
