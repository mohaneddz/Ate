# Install Ate on Windows

The packaged release needs **Windows 10 or 11, 64-bit**, internet access, and
the original **Webetu 2.5.0 APK or XAPK**. It does not need Python. Do not send
your student number or password with the package.

1. Extract the whole `Ate-0.4.0-win64.zip` archive.
2. Double-click `install.cmd` in the extracted folder. Keep its `scripts`
   subfolder beside it.
3. Enter the path to your own original Webetu APK/XAPK. Dragging the file into
   the terminal usually pastes its path.
4. Enter your student number and password. Password input is hidden. Choose a
   dorm and main restaurant from the live list, then choose the number of days
   to keep booked.
5. The installer saves your account encrypted for your Windows user, adds
   `ate` to your user PATH, installs the background task, and starts one check.
6. Open a **new Command Prompt** and run `ate doctor`, then `ate show`.

If `ate` is not recognized in a new Command Prompt, sign out of Windows and
sign back in so Explorer picks up the updated user PATH. You can also run
`%LOCALAPPDATA%\Ate\bin\ate.exe` directly.

Use `ate 3` to maintain a rolling three days, `ate until 10-12` for an inclusive
end date, `ate plan` to preview, and `ate log 30` for recent reservations and
activity. `ate help` lists all commands. Breakfast and dinner use your chosen
dorm; Sunday–Thursday lunch uses your chosen main restaurant. Friday and
Saturday have no automatic lunch.

To check an APK/XAPK before installing, run `ate check-app PATH` from any copy
of the packaged executable. It only reads the file on your PC.

## What starts automatically

Windows Task Scheduler registers a task named `Ate` for your Windows user. It
runs when you sign in and every five minutes while a network is
available. It uses `wscript.exe` to keep the run hidden. The CLI checks the
standing order, skips existing meals, confirms each new reservation, and stops
making API calls after a successful daily run. It tries again later after a
temporary failure. A powered-off or sleeping PC cannot run the task; the next
available check catches up within the service's three-day booking window.

The task is configured to run while you are signed in, including when your
screen is locked. `ate doctor` shows the order, scheduler, and latest result.
`%LOCALAPPDATA%\Ate\state\runs.jsonl` records local activity. The
profile and reservation snapshots in `state` are encrypted with Windows DPAPI.

## Update or remove

To update, extract a newer archive and run its `install.cmd`. Your encrypted
account and standing order remain in the same user data folder. To remove the
program, run `uninstall.cmd` from the archive or from
`%LOCALAPPDATA%\Ate\bin`. This removes the task, `ate` executable,
and PATH entry. It preserves the encrypted account data so reinstalling is
easy. To remove that data too, run:

```cmd
powershell -NoProfile -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\Ate\bin\scripts\uninstall-package.ps1" -PurgeData
```

When updating from Couscous Cron 0.3.0, the installer copies its encrypted
account, order, and local history into Ate's data folder, replaces its scheduled
task, and removes its PATH entry. The old data folder remains as a backup.

## If setup cannot connect

Setup needs the two Webetu services to authenticate and list restaurants. If
it stops, no background task is installed. Run `install.cmd` again once the
service is available. The importer supports the bytecode in Webetu 2.5.0; a
newer original app may need a CLI update.
