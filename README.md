![Ate](screenshots/cover.avif)

# Ate

Ate keeps your Webetu meals booked while your computer is signed in and online. It checks existing reservations before booking breakfast and dinner at your dorm, lunch at your dorm on Friday and Saturday, and lunch at your main restaurant Sunday through Thursday.

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
| `res telegram bot.env` | Pair a Telegram bot for alerts; `res telegram test` and `res telegram off` also work. |
| `res help` | See all commands. |

Webetu opens reservations only a few days ahead. Ate checks again later; it cannot run while your computer is off or asleep. Cancelling `res auth` with Ctrl+C keeps the prior account, and an interrupted save is recovered on the next command.

If the university login is rejected twice in a row, 30 minutes apart, Ate suspends automatic booking so it does not keep retrying a bad password. A suspended run writes one line to the log per day, and `res show`, `res log`, `res plan` and `res doctor` all warn about it. Run `res auth` to sign in again. A one-off server error at any other step only delays the next attempt.

## Telegram alerts

Create a bot with [@BotFather](https://t.me/BotFather), then put its HTTP API token in a file as `http=123456789:AA...`. Run `res telegram bot.env` (or `res telegram` to paste the token hidden), open the link it prints, press Start, and confirm your name. Only that private chat receives alerts. The token is stored encrypted for your Windows user, so you can delete the file afterwards.

Scheduled runs message you when meals are booked, when the first failure of a streak happens, when booking is suspended (repeated daily), and when it recovers. Commands you run yourself, including `res sync`, stay silent. A failed alert is logged and never affects booking.

## Always-on server and Telegram commands

Booking only runs while your PC is awake. On a Debian or Ubuntu server that stays on, `scripts/install-server.sh` installs Ate as a system service that runs `ate serve`: the scheduled booking check plus a Telegram bot that answers commands within a second or two, even when your PC is off. Build the wheel with `pip wheel . --no-deps`, copy it and the script to the server, and run `sh install-server.sh ate_cli-VERSION-py3-none-any.whl` as root. Then run `ate auth`, `ate telegram bot.env`, and `systemctl start ate`. The server's IP must be able to reach Webetu; an Algerian address is safest.

Only the chat paired with `ate telegram` is answered. Commands: `/status`, `/today`, `/plan`, `/sync`, `/log`, `/date`, `/days`, `/until`, `/pause`, `/resume`, `/interval`, `/config`, `/depots`, `/doctor` and `/help`. Signing in is the one thing that stays in the terminal, so your password never passes through chat.

## Local and cloud switches

`res local on|off` switches booking on this machine (its scheduled task) on or off. `res cloud on|off` does the same for your server by pausing or resuming the server's standing order over SSH, so the Telegram bot keeps answering either way. Run `res cloud setup user@host [port]` once to save the server. The two are independent: with both on, both machines check and book, and each looks at the live reservations before every write, so a meal is never booked twice. `res local` and `res cloud` with no argument show the current state, and `res doctor` lists both. If your SSH key has a passphrase, load it first with `ssh-add`.

## Remove

On Windows, run `uninstall.bat` from the ZIP or Program Files. On Linux, run `~/.local/share/ate/uninstall.sh`. Both keep account data for an easy reinstall. On Linux, add `--purge-data` to delete it too. On Windows, use `scripts/uninstall-package.ps1 -PurgeData` from the ZIP to remove it.

## Develop

Python 3.11+ is needed for source work. Run `python -m pip install -e .` and `python -m unittest discover -s tests -q`. The release workflow tests Windows and Linux, builds both archives, and publishes them from a version tag.
