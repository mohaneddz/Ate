# Couscous Cron 🍽️

A small Windows CLI that reserves Webetu meals when your PC is online. Based on
the requests recovered from the original Webetu 2.5.0 Android app and verified
against a personal account.

- Breakfast and dinner: your dorm, every day.
- Lunch: your chosen main restaurant, Sunday–Thursday.
- Existing bookings are checked first; conflicting bookings stop the run.
- Each submission is read back from the server before being called confirmed.
- Passwords and imported app signing material stay in Windows DPAPI encrypted
  files under `.reserve/`. Runtime session tokens stay in memory.
- Credentials, APKs, analysis output, and local logs are excluded from Git.

## Setup

Use Python 3.11+ on Windows, under the Windows user who will run the schedule:

```powershell
python -m pip install -e ".[import]"
python -m reserve_cli setup --credentials info.env --app original.xapk --dorm-id 185 --main-id 569
```

The two IDs above are examples; use IDs for your own chosen locations. The
credential file uses `student=...` and `password=...`. Setup leaves that original
file in place; it is not needed for subsequent runs. Do not commit it.

The importer reads the signing constant from your own original APK/XAPK with
[hermes-dec](https://github.com/P1sec/hermes-dec). It accepts the bytecode used by
Webetu 2.5.0 and stops if it cannot identify the expected signing code.

## Use it

The package installs `res.exe` into Python's Scripts directory. If that
directory is already on your user PATH, open a **new Command Prompt** and use:

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

The `Couscous Cron` task checks at sign-in and every five minutes. Windows requires
a network connection before starting it. After a successful run it makes no more
API calls that day unless the order changes or you run `run --force`. Missed
checks are picked up when the PC is available again. Transient failures back off
from five minutes to one hour; authentication rejection suspends automatic
login attempts. The task runs while your Windows user is signed in, including
when the screen is locked. It does not wake a sleeping or powered-off PC.

The scheduler uses `pythonw.exe` when available to avoid opening terminal windows.
Results and errors go to `.reserve/runs.jsonl`. The `--state-dir PATH` option
goes before the command when using a different local data folder.

```powershell
Get-ScheduledTaskInfo -TaskName 'Couscous Cron'
Get-Content .reserve/runs.jsonl -Tail 20
Disable-ScheduledTask -TaskName 'Couscous Cron'
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
