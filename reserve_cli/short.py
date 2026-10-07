"""Friendly terminal entry point for the personal reservation client."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import getpass
import io
import json
import os
from pathlib import Path
import re
from contextlib import redirect_stdout
import sys
from zoneinfo import ZoneInfo

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import cli
from .api import ApiError, Client
from .auth import load_credentials
from .booking import BookingError, MEALS, make_plan, meal_number, order_dates
from .config import interval_label, interval_minutes, parse_interval, set_interval
from .store import Store, StoreError
from .paths import default_state_dir
from .signing import SIGNING_KEY

STATE_DIR = default_state_dir()
MAX_DAYS = 366


def prog() -> str:
    """The command the user actually typed, so help and errors match it."""
    name = Path(sys.argv[0]).stem.lower()
    return name if name in ("res", "ate") else "res"


def local_now() -> datetime:
    return datetime.now(ZoneInfo("Africa/Algiers"))


def parse_day(value: str, today: date | None = None) -> date:
    """Accept YYYY-MM-DD or MM-DD; omitted year means next occurrence."""
    today = today or local_now().date()
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    match = re.fullmatch(r"(\d{1,2})-(\d{1,2})", value)
    if not match:
        raise ValueError("Use MM-DD or YYYY-MM-DD, for example 10-05.")
    month, day = map(int, match.groups())
    for year in range(today.year, today.year + 5):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate > today:
            return candidate
    raise ValueError("That month and day are not a valid future date.")


def read_activity(path: Path, earliest: date) -> list[dict]:
    if not path.exists():
        return []
    events = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
                when = datetime.fromisoformat(event["at"])
                message = event.get("message")
                # The older runner recorded both preview rows and outcomes.
                # Keep the outcome to avoid showing every booking twice.
                if isinstance(message, str) and re.match(r"^\d{4}-\d{2}-\d{2}\s{2,}", message):
                    continue
                if when.date() >= earliest and isinstance(message, str):
                    events.append(event)
            except (ValueError, KeyError, TypeError):
                continue
    return events


def append_activity(store: Store, message: str) -> None:
    store.append_log(json.dumps({"at": local_now().isoformat(), "message": message}, ensure_ascii=False))


def order_text(order: dict | None, today: date) -> str:
    if not order:
        return "No standing order"
    if order.get("kind") == "days":
        text = f"Next {order['days']} day(s), rolling"
    else:
        text = f"Through {order['until']}"
    if order.get("paused"):
        text += "  •  PAUSED"
    elif order.get("kind") == "until" and date.fromisoformat(order["until"]) <= today:
        text += "  •  FINISHED"
    else:
        text += "  •  ACTIVE"
    return text


def plain(value: object, style: str | None = None) -> Text:
    # Rich markup must never parse names or response text from the service.
    return Text(str(value), style=style)


def heading(console: Console, title: str, subtitle: str = "") -> None:
    text = Text(title, style="bold bright_cyan")
    if subtitle:
        text.append("\n" + subtitle, style="dim")
    console.print(Panel(text, border_style="cyan", padding=(0, 2), expand=False))


def bookings_table(rows: list[dict], *, title: str, newest_first: bool = False) -> Table:
    table = Table(title=title, box=box.ROUNDED, header_style="bold bright_white",
                  border_style="bright_black", show_lines=False, pad_edge=True)
    table.add_column("Date", style="cyan", no_wrap=True)
    table.add_column("Day", style="dim", no_wrap=True)
    table.add_column("Meal", no_wrap=True)
    table.add_column("Restaurant", overflow="fold")
    table.add_column("ID", justify="right", style="dim", no_wrap=True)
    colors = {1: "yellow", 2: "bright_magenta", 3: "bright_blue"}
    ordered = sorted(rows, key=lambda r: (r["date_reserve"], meal_number(r), str(r.get("id", ""))),
                     reverse=newest_first)
    for row in ordered:
        day = date.fromisoformat(row["date_reserve"])
        meal = meal_number(row)
        table.add_row(day.isoformat(), day.strftime("%a"), plain(MEALS[meal].title(), colors[meal]),
                      plain(row.get("depot_fr") or row.get("depot_ar") or "?"),
                      plain(row.get("id", "?")))
    return table


def plan_table(plan) -> Table:
    table = Table(title="Booking plan", box=box.ROUNDED, header_style="bold bright_white", border_style="bright_black")
    table.add_column("Date", style="cyan", no_wrap=True)
    table.add_column("Meal")
    table.add_column("Restaurant")
    table.add_column("State", justify="right")
    for item in plan:
        state = plain("Booked" if item.existing_id else "Available to book",
                      "green" if item.existing_id else "yellow")
        table.add_row(item.day.isoformat(), item.label.title(),
                      plain(item.depot.get("nameFR") or item.depot.get("nameAR") or "?"), state)
    return table


def activity_table(events: list[dict]) -> Table:
    table = Table(title="CLI activity", box=box.ROUNDED, header_style="bold bright_white", border_style="bright_black")
    table.add_column("When", style="cyan", no_wrap=True)
    table.add_column("Event", overflow="fold")
    for event in reversed(events):
        message = event["message"]
        color = "red" if message.startswith("Error:") else "green" if message.startswith("Confirmed:") else "white"
        table.add_row(datetime.fromisoformat(event["at"]).strftime("%Y-%m-%d %H:%M"), plain(message, color))
    return table


def fetch_bookings(store: Store) -> tuple[list[dict], str | None]:
    profile = store.read("profile")
    if not profile:
        raise BookingError(f"Account setup is missing. Run {prog()} auth first.")
    client = Client(profile)
    try:
        client.login()
        rows = client.reservations()
        store.write("reservation_cache", {"at": local_now().isoformat(), "rows": rows})
        return rows, None
    except ApiError:
        cached = store.read("reservation_cache")
        if cached:
            return cached["rows"], cached["at"]
        raise
    finally:
        client.close()


def legacy(console: Console, args: list[str]) -> int:
    # Reuse the original CLI's locking, journal, retry, and duplicate checks.
    output = io.StringIO()
    with redirect_stdout(output):
        result = cli.main(args)
    messages = [line for line in output.getvalue().splitlines() if line.strip()]
    preview = []
    remainder = []
    for message in messages:
        match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\s+(breakfast|lunch|dinner)\s+(.+?)\s+\[(already booked #\d+|to reserve)\]", message)
        if match:
            preview.append(match.groups())
        else:
            remainder.append(message)
    if preview:
        table = Table(title="Booking check", box=box.ROUNDED, border_style="bright_black", header_style="bold bright_white")
        table.add_column("Date", style="cyan")
        table.add_column("Meal")
        table.add_column("Restaurant")
        table.add_column("State", justify="right")
        for day, meal, restaurant, state in preview:
            table.add_row(day, meal.title(), plain(restaurant),
                          plain("Booked" if state.startswith("already") else "To reserve",
                                "green" if state.startswith("already") else "yellow"))
        console.print(table)
    for message in remainder:
        if message.startswith("Error:"):
            console.print(plain(message, "bold red"))
        elif message.startswith(("Confirmed:", "Already reserved:")):
            console.print(plain("✓ " + message, "green"))
        elif message.startswith("Standing order saved"):
            console.print(plain("✓ " + message, "green"))
        else:
            console.print(plain(message, "white"))
    return result


def help_screen(console: Console) -> None:
    name = prog()
    heading(console, f"{name}  /  Ate", "Webetu meal reservations • Algeria time")
    table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    table.add_column("Command", style="bold bright_cyan", no_wrap=True)
    table.add_column("What it does", style="white")
    for command, detail in [
        (f"{name} auth [FILE]", "Sign in or refresh account details; .env, .md and JSON work."),
        (f"{name} 3", "Keep the next 3 days booked; run now and keep checking online."),
        (f"{name} until 10-12", "Book through October 12; year is optional."),
        (f"{name} show", "Live table of current and upcoming reservations."),
        (f"{name} plan", "Preview what the standing order would book."),
        (f"{name} log 30", "Past 30 days of reservations and CLI activity."),
        (f"{name} date 10-05", "Book a specific date within the service's 3-day window."),
        (f"{name} sync", "Check and fulfill the current order now."),
        (f"{name} config", "View or change check interval, order, and account settings."),
        (f"{name} pause / resume", "Pause or resume automatic booking."),
        (f"{name} depots", "Show available restaurants and IDs."),
        (f"{name} doctor", "Show setup, scheduler and recent run health."),
    ]:
        table.add_row(command, detail)
    console.print(table)
    console.print(plain("Breakfast and dinner use the dorm. Lunch uses the main restaurant Sunday–Thursday.", "dim"))


def auth_wizard(console: Console, store: Store, credential_file: Path | None = None) -> int:
    import uuid

    with store.lock():
        existing = store.read("profile") or {}
        heading(console, "Ate account", "Sign in and choose your restaurants")
        if credential_file is None:
            default_student = existing.get("student")
            label = "Student number" + (" [current]" if default_student else "") + ": "
            student = console.input(label).strip() or default_student
            entered_password = getpass.getpass("Password (hidden, Enter keeps current): " if existing else "Password (hidden): ")
            password = entered_password or existing.get("password")
            credentials = {}
        else:
            credentials = load_credentials(credential_file)
            student, password = credentials["student"], credentials["password"]
        if not student or not password:
            raise ValueError("Student number and password are required.")
        if existing and student != existing.get("student"):
            raise BookingError("This data belongs to another student. Use a separate state directory for another account.")
        profile = {"student": student, "password": password, "signing_key": SIGNING_KEY}
        client = Client(profile)
        try:
            console.print(plain("Checking your account and restaurants…", "dim"))
            client.login()
            depots = client.depots()
        finally:
            client.close()
        dorm_options = [d for d in depots if d.get("breakfast") and d.get("dinner")]
        main_options = [d for d in depots if d.get("lunch")]
        if not dorm_options or not main_options:
            raise BookingError("The meal service did not offer suitable restaurants to this account.")

        def choose(label: str, field: str, options: list[dict]) -> int:
            table = Table(title=label, box=box.ROUNDED, border_style="bright_black")
            table.add_column("ID", style="cyan", justify="right")
            table.add_column("Restaurant")
            for item in options:
                table.add_row(str(item["id"]), plain(item.get("nameFR") or item.get("nameAR") or "?"))
            console.print(table)
            permitted = {int(item["id"]) for item in options}
            supplied = credentials.get(field)
            previous = existing.get(field)
            if supplied is not None:
                if supplied.isdecimal():
                    if int(supplied) not in permitted:
                        raise ValueError(f"The {field} in the file is not an available restaurant ID.")
                    console.print(plain(f"Using {label} ID {supplied} from the file.", "dim"))
                    return int(supplied)
                normalized = re.sub(r"\W+", "", supplied.casefold())
                matches = [int(item["id"]) for item in options
                           if any(normalized == re.sub(r"\W+", "", str(item.get(name) or "").casefold())
                                  for name in ("nameFR", "nameAR"))]
                if len(matches) == 1:
                    console.print(plain(f"Matched {label} to ID {matches[0]} from the file.", "dim"))
                    return matches[0]
                if previous in permitted:
                    console.print(plain(f"The {field} name in the file did not match; keeping current ID {previous}.", "yellow"))
                    return previous
                console.print(plain(f"The {field} name in the file did not match. Choose an ID shown above.", "yellow"))
            prompt = f"{label} ID" + (f" [{previous}]" if previous in permitted else "") + ": "
            for _ in range(3):
                raw = console.input(prompt).strip()
                if not raw and previous in permitted:
                    return previous
                if raw.isdecimal() and int(raw) in permitted:
                    return int(raw)
                console.print(plain("Choose an ID shown in the table.", "yellow"))
            raise ValueError("Restaurant selection was not completed.")

        profile["dorm_id"] = choose("Dorm for breakfast and dinner", "dorm_id", dorm_options)
        profile["main_id"] = choose("Main restaurant for Sunday–Thursday lunch", "main_id", main_options)
        order = store.read("order")
        if not order:
            raw_days = credentials.get("days") or console.input("Keep the next how many days booked? [3]: ").strip() or "3"
            if not raw_days.isdecimal() or not 1 <= int(raw_days) <= MAX_DAYS:
                raise ValueError("Choose a number from 1 to 366 days.")
            order = {"kind": "days", "days": int(raw_days), "paused": False, "revision": str(uuid.uuid4())}
        with store.transaction("profile", "order", "run_state"):
            store.write("profile", profile)
            store.write("order", order)
            store.write("run_state", {})
            protection = ("encrypted for this Windows user" if os.name == "nt"
                          else "stored in files only your Linux user can read")
            console.print(plain(f"✓ Account ready. Login details are {protection}.", "green"))
            console.print(plain("Your standing order is ready for the background checker.", "dim"))
        return 0


def doctor(console: Console, store: Store) -> None:
    import subprocess
    import shutil

    today = local_now().date()
    profile = store.read("profile")
    order = store.read("order")
    run_state = store.read("run_state", {})
    activity = read_activity(store.directory / "runs.jsonl", today - timedelta(days=30))
    task = "Unknown"
    if sys.platform == "win32":
        try:
            process = subprocess.run(["schtasks", "/Query", "/TN", "Ate", "/FO", "LIST"],
                                     capture_output=True, text=True, errors="replace", timeout=10)
            task = "Installed" if process.returncode == 0 else "Missing"
        except (OSError, subprocess.TimeoutExpired):
            task = "Could not check"
    elif sys.platform.startswith("linux"):
        try:
            process = subprocess.run(["systemctl", "--user", "is-enabled", "ate.timer"],
                                     capture_output=True, text=True, errors="replace", timeout=10)
            task = "Installed" if process.returncode == 0 else "Missing"
        except (OSError, subprocess.TimeoutExpired):
            task = "Could not check"
    table = Table(title="Health check", box=box.ROUNDED, show_header=False, border_style="bright_black")
    table.add_column("Item", style="cyan")
    table.add_column("Value")
    table.add_row("Account", plain("Configured" if profile else "Setup needed", "green" if profile else "red"))
    table.add_row("Order", plain(order_text(order, today)))
    table.add_row("Scheduler", plain(task, "green" if task == "Installed" else "yellow"))
    available = bool(shutil.which("res") or shutil.which("ate"))
    if not available and sys.platform == "win32" and getattr(sys, "frozen", False):
        # The installer updates the user PATH, but a terminal opened before
        # installation still has its old process environment.
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                user_path = winreg.QueryValueEx(key, "Path")[0]
            installed_bin = os.path.normcase(os.path.normpath(str(Path(sys.executable).parent)))
            available = any(
                os.path.normcase(os.path.normpath(os.path.expandvars(entry.strip().strip('"')))) == installed_bin
                for entry in user_path.split(";") if entry.strip()
            )
        except OSError:
            pass
    table.add_row("Command in PATH", plain("Yes" if available else "No", "green" if available else "yellow"))
    table.add_row("Last completed", plain(run_state.get("completed", "—")))
    table.add_row("Automatic login", plain("Suspended" if run_state.get("authentication_blocked") else "Ready",
                                                 "red" if run_state.get("authentication_blocked") else "green"))
    table.add_row("Recent log entries", str(len(activity)))
    console.print(table)


def run(argv: list[str], console: Console | None = None, store: Store | None = None) -> int:
    console = console or Console(highlight=False)
    store = store or Store(STATE_DIR)
    today = local_now().date()
    if not argv or argv[0] in ("help", "-h", "--help", "?"):
        help_screen(console)
        return 0
    command = argv[0].lower()
    if command == "config":
        if len(argv) == 2 and argv[1] == "--minutes":
            console.print(str(interval_minutes(store)))
            return 0
        if len(argv) == 1:
            heading(console, "Ate settings")
            table = Table(box=box.SIMPLE, show_header=False)
            table.add_column("Setting", style="cyan")
            table.add_column("Value")
            table.add_row("Check interval", interval_label(interval_minutes(store)))
            table.add_row("Standing order", order_text(store.read("order"), today))
            profile = store.read("profile") or {}
            table.add_row("Account", str(profile.get("student", "Not configured")))
            table.add_row("Dorm ID", str(profile.get("dorm_id", "Not configured")))
            table.add_row("Main restaurant ID", str(profile.get("main_id", "Not configured")))
            console.print(table)
            console.print(f"Change: {prog()} config interval 15m | 2h | 1d")
            console.print(f"Order: {prog()} config days 3 | until MM-DD | pause | resume")
            console.print(f"Account or restaurants: {prog()} config account")
            return 0
        if len(argv) == 3 and argv[1] == "interval":
            minutes = parse_interval(argv[2])
            installed = set_interval(store, minutes)
            console.print(plain(f"Check interval set to {interval_label(minutes)}."))
            if not installed:
                console.print(plain("The scheduler is not installed yet; the installer will use this setting.", "yellow"))
            return 0
        if len(argv) == 3 and argv[1] == "days":
            return run([argv[2]], console, store)
        if len(argv) == 3 and argv[1] == "until":
            return run(["until", argv[2]], console, store)
        if len(argv) == 2 and argv[1] in ("pause", "resume"):
            return run([argv[1]], console, store)
        if len(argv) == 2 and argv[1] == "account":
            return run(["auth"], console, store)
        raise ValueError(f"Use {prog()} config, or {prog()} config interval 15m | 2h | 1d.")
    if command in ("auth", "setup"):
        if len(argv) > 2:
            raise ValueError(f"Use {prog()} auth [CREDENTIAL-FILE].")
        credential_file = Path(argv[1].strip().strip('"')).expanduser() if len(argv) == 2 else None
        return auth_wizard(console, store, credential_file)
    if command == "background":
        if len(argv) == 3 and argv[1] == "--state-dir":
            store = Store(Path(argv[2]))
        elif len(argv) != 1:
            raise ValueError("Background runner takes no arguments except --state-dir PATH.")
        return cli.main(["--state-dir", str(store.directory), "run"])
    if command.isdecimal():
        if len(argv) != 1 or not 1 <= int(command) <= MAX_DAYS:
            raise ValueError(f"Use {prog()} N with a number from 1 to 366.")
        heading(console, f"Reserve the next {int(command)} days", "Rolling order • checking available dates now")
        result = legacy(console, ["order", "days", command])
        if result:
            return result
        append_activity(store, f"Order changed: rolling next {int(command)} day(s).")
        return legacy(console, ["run", "--force"])
    if command == "until":
        if len(argv) != 2:
            raise ValueError(f"Use {prog()} until MM-DD or {prog()} until YYYY-MM-DD.")
        target = parse_day(argv[1], today)
        if not today < target <= today + timedelta(days=MAX_DAYS):
            raise ValueError("Choose a future date within the next 366 days.")
        heading(console, f"Reserve through {target.isoformat()}", "Fixed end date • checking available dates now")
        result = legacy(console, ["order", "until", target.isoformat()])
        if result:
            return result
        append_activity(store, f"Order changed: through {target.isoformat()}.")
        return legacy(console, ["run", "--force"])
    if command in ("show", "today"):
        if len(argv) != 1:
            raise ValueError(f"Use {prog()} {command} without extra arguments.")
        with store.lock():
            rows, cache_time = fetch_bookings(store)
            order = store.read("order")
        rows = [row for row in rows if row["date_reserve"] >= today.isoformat()]
        if command == "today":
            rows = [row for row in rows if row["date_reserve"] == today.isoformat()]
        heading(console, "Your reservations", order_text(order, today))
        if cache_time:
            console.print(plain(f"Offline view • last updated {cache_time}", "yellow"))
        if rows:
            console.print(bookings_table(rows, title=f"{len(rows)} confirmed meal(s)"))
        else:
            console.print(plain("No matching reservations yet.", "yellow"))
        return 0
    if command == "log":
        if len(argv) > 2 or len(argv) == 2 and not argv[1].isdecimal():
            raise ValueError(f"Use {prog()} log [days], for example {prog()} log 30.")
        count = int(argv[1]) if len(argv) == 2 else 30
        if not 1 <= count <= MAX_DAYS:
            raise ValueError("Log period must be from 1 to 366 days.")
        earliest = today - timedelta(days=count - 1)
        with store.lock():
            rows, cache_time = fetch_bookings(store)
            activity = read_activity(store.directory / "runs.jsonl", earliest)
        history = [row for row in rows if earliest.isoformat() <= row["date_reserve"] <= today.isoformat()]
        heading(console, f"Last {count} days", f"{earliest} through {today}")
        if cache_time:
            console.print(plain(f"Offline reservations • last updated {cache_time}", "yellow"))
        if history:
            console.print(bookings_table(history, title=f"{len(history)} reservation(s)", newest_first=True))
        else:
            console.print(plain("No reservations in this period.", "dim"))
        if activity:
            console.print(activity_table(activity))
        else:
            console.print(plain("No CLI activity in this period.", "dim"))
        return 0
    if command == "plan":
        if len(argv) != 1:
            raise ValueError(f"Use {prog()} plan without extra arguments.")
        with store.lock():
            order = store.read("order")
            if not order:
                raise BookingError(f"No standing order. Use {prog()} 3 or {prog()} until MM-DD.")
            days, deferred = order_dates(order, today)
            profile = store.read("profile")
            client = Client(profile)
            try:
                client.login()
                rows = client.reservations()
                depots = client.depots()
                store.write("reservation_cache", {"at": local_now().isoformat(), "rows": rows})
                store.write("depot_cache", depots)
                cache_time = None
            except ApiError:
                cached = store.read("reservation_cache")
                depots = store.read("depot_cache")
                if not cached or not depots:
                    raise
                rows, cache_time = cached["rows"], cached["at"]
            finally:
                client.close()
            plan = make_plan(days, profile, depots, rows)
        heading(console, "Next booking plan", order_text(order, today))
        if cache_time:
            console.print(plain(f"Reservations cached at {cache_time}", "yellow"))
        if plan:
            console.print(plan_table(plan))
        else:
            console.print(plain("Nothing within the current booking window.", "yellow"))
        if deferred:
            console.print(plain(f"{deferred} later day(s) wait for the 3-day booking window.", "dim"))
        return 0
    if command == "depots":
        if len(argv) != 1:
            raise ValueError(f"Use {prog()} depots without extra arguments.")
        profile = store.read("profile")
        if not profile:
            raise BookingError("Account setup is missing.")
        client = Client(profile)
        try:
            client.login()
            depots = client.depots()
            store.write("depot_cache", depots)
        finally:
            client.close()
        heading(console, "Available restaurants")
        table = Table(box=box.ROUNDED, border_style="bright_black", header_style="bold bright_white")
        table.add_column("ID", style="cyan", justify="right")
        table.add_column("Restaurant")
        table.add_column("Meals")
        for depot in depots:
            choices = ", ".join(name for name in MEALS.values() if depot.get(name))
            table.add_row(str(depot["id"]), plain(depot.get("nameFR") or depot.get("nameAR")), choices)
        console.print(table)
        return 0
    if command == "doctor":
        if len(argv) != 1:
            raise ValueError(f"Use {prog()} doctor without extra arguments.")
        heading(console, "Ate")
        doctor(console, store)
        return 0
    if command in ("sync", "pause", "resume"):
        if len(argv) != 1:
            raise ValueError(f"Use {prog()} {command} without extra arguments.")
        heading(console, {"sync": "Checking your order", "pause": "Pause bookings", "resume": "Resume bookings"}[command])
        result = legacy(console, ["run", "--force"] if command == "sync" else ["order", command])
        if not result and command in ("pause", "resume"):
            append_activity(store, f"Automatic booking {command}d.")
        return result
    if command in ("date", "preview"):
        if len(argv) != 2:
            raise ValueError(f"Use {prog()} {command} MM-DD.")
        target = parse_day(argv[1], today)
        heading(console, f"{command.title()} {target.isoformat()}")
        arguments = ["reserve", "--date", target.isoformat()]
        if command == "date":
            arguments.append("--apply")
        result = legacy(console, arguments)
        if command == "date":
            append_activity(store, f"Manual booking requested for {target.isoformat()}: " +
                            ("completed" if result == 0 else "check result"))
        return result
    raise ValueError(f"Unknown command. Run {prog()} help to see available commands.")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except (ApiError, BookingError, StoreError, ValueError, KeyError, TypeError, OSError) as exc:
        # API failures are already sanitized by Client. Avoid printing raw response data.
        Console(highlight=False).print(plain(f"Error: {exc}", "bold red"))
        return 1
    except (EOFError, KeyboardInterrupt):
        Console(highlight=False).print(plain("Cancelled; account details were not changed.", "yellow"))
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
