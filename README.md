![Ate](screenshots/cover.avif)

# Ate

Ate keeps your Webetu meals booked while your computer is signed in and online. It checks existing reservations before booking breakfast and dinner at your dorm and Sunday through Thursday lunch at your main restaurant.

## Install

**Windows 10/11:** Download and extract the [latest Windows ZIP](https://github.com/mohaneddz/Ate/releases/latest). Double-click `install.bat`, approve the administrator prompt, and enter your account and restaurant details. Python is not needed. The app goes to Program Files; your account data stays encrypted for your Windows user.

**Linux:** Download and extract the [latest Linux archive](https://github.com/mohaneddz/Ate/releases/latest), then run `./install.sh` as your regular user. The archive includes a standalone executable, so Python is not needed. A running systemd user session is required for background checks. The app goes to `~/.local/share/ate`, and `res` is linked into `~/.local/bin` (add that folder to PATH if needed). Account files are readable only by your Linux user. Linux does not encrypt them at rest.

Both installers ask how many days to keep booked and start background checks. Updates use the same installer and keep your account and settings.

## Commands

| Command | Purpose |
| --- | --- |
| `res show` | See current and upcoming meals. |
| `res 3` | Keep the next three days booked. |
| `res until 10-12` | Keep booking through October 12. |
| `res config` | See account, order, and check settings. |
| `res config interval 15m` | Check every 15 minutes; `2h` and `1d` also work (up to 7 days). |
| `res config days 5` | Change the rolling order. |
| `res config account` | Change your password or restaurants. |
| `res pause` / `res resume` | Stop or restart automatic booking. |
| `res log 30` | See recent reservations and activity. |
| `res help` | See all commands. |

Webetu opens reservations only a few days ahead. Ate checks again later; it cannot run while your computer is off or asleep. Cancelling `res auth` with Ctrl+C keeps the prior account, and an interrupted save is recovered on the next command.

## Remove

On Windows, run `uninstall.bat` from the ZIP or Program Files. On Linux, run `~/.local/share/ate/uninstall.sh`. Both keep account data for an easy reinstall. On Linux, add `--purge-data` to delete it too. On Windows, use `scripts/uninstall-package.ps1 -PurgeData` from the ZIP to remove it.

## Develop

Python 3.11+ is needed for source work. Run `python -m pip install -e .` and `python -m unittest discover -s tests -q`. The release workflow tests Windows and Linux, builds both archives, and publishes them from a version tag.
