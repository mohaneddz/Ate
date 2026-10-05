# Install Ate on Windows

The packaged release needs **Windows 10 or 11, 64-bit** and internet access.
It does not need Python or an APK/XAPK. Keep your account details on your own PC.

1. Extract the whole `Ate-0.5.0-win64.zip` archive.
2. Double-click `install.bat` in the extracted folder. Keep its `scripts`
   subfolder beside it.
3. Enter your student number and password. Password input is hidden. Choose a
   dorm and main restaurant from the live list, then choose the number of days
   to keep booked.
4. The installer saves your account encrypted for your Windows user, adds `res`
   to your user PATH, installs the background task, starts one check, and opens
   a ready terminal showing your reservations.
5. In that terminal, try `res 3` to keep the next three days booked.

## Install directly from a clone

Install Python 3.11 or newer, then run `git clone https://github.com/mohaneddz/Ate.git`,
open the `Ate` folder, and double-click `install.bat`. It installs the small
Python package, prompts for your account and restaurants, registers the same
background task, and opens a ready terminal. You can also run
`python -m pip install -e .` followed by `res auth` and
`powershell -ExecutionPolicy Bypass -File scripts/install-schedule.ps1`.

If `res` is not recognized in a terminal you opened yourself, sign out of
Windows and sign back in so Explorer picks up the updated user PATH. You can
also run `%LOCALAPPDATA%\Ate\bin\ate.exe` directly.

Use `res 3` to maintain a rolling three days, `res until 10-12` for an inclusive
end date, `res plan` to preview, and `res log 30` for recent reservations and
activity. `res help` lists all commands. Breakfast and dinner use your chosen
dorm; Sunday–Thursday lunch uses your chosen main restaurant. Friday and
Saturday have no automatic lunch. (`res` and `ate` are the same command.)

Run `res auth` whenever you need to recheck login or change a password or
restaurant. The command verifies the new details before saving them and keeps
your existing standing order. To import a file instead of typing credentials,
use `res auth info.env` or `res auth credentials.md`. JSON also works. Example
file:

```text
student=YOUR_STUDENT_NUMBER
password=YOUR_PASSWORD
dorm_id=YOUR_DORM_ID
main_id=YOUR_MAIN_RESTAURANT_ID
days=3
```

The restaurant IDs and days are optional. Without IDs, the command lists the
restaurants available to your account and asks you to choose. `days` is used
only when no standing order exists. A Markdown file may use `student: ...` and
`password: ...` lines or a two-column table. Keep this file out of Git;
`*.env` and `credentials*` files are ignored by this repository.
Source and packaged commands share `%LOCALAPPDATA%\Ate\state`. The source
installer copies an older checkout's `.reserve` data there if needed.

## What starts automatically

Windows Task Scheduler registers a task named `Ate` for your Windows user. It
runs when you sign in and every five minutes while a network is
available. It uses `wscript.exe` to keep the run hidden. The CLI checks the
standing order, skips existing meals, confirms each new reservation, and stops
making API calls after a successful daily run. It tries again later after a
temporary failure. A powered-off or sleeping PC cannot run the task; the next
available check catches up within the service's three-day booking window.

The task is configured to run while you are signed in, including when your
screen is locked. `res doctor` shows the order, scheduler, and latest result.
`%LOCALAPPDATA%\Ate\state\runs.jsonl` records local activity. The
profile and reservation snapshots in `state` are encrypted with Windows DPAPI.

## Update or remove

To update, extract a newer archive and run its `install.bat`. Your encrypted
account and standing order remain in the same user data folder. To remove the
program, run `uninstall.bat` from the archive or from
`%LOCALAPPDATA%\Ate\bin`. This removes the task, `ate` executable,
and PATH entry. It preserves the encrypted account data so reinstalling is
easy. To remove that data too, run:

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Ate\bin\scripts\uninstall-package.ps1" -PurgeData
```

## If setup cannot connect

Setup needs the two Webetu services to authenticate and list restaurants. If
it stops, no background task is installed. Run `install.bat` again once the
service is available. If the service changes its signing requirements, Ate
will need an update.
