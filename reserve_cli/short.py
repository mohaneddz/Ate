"""Friendly terminal entry point for the personal reservation client."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import io
import json
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
from .booking import BookingError, MEALS, make_plan, meal_number, order_dates
from .store import Store, StoreError

STATE_DIR = Path(__file__).resolve().parents[1] / ".reserve"
MAX_DAYS = 366


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
    with (store.directory / "runs.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": local_now().isoformat(), "message": message}, ensure_ascii=False) + "\n")


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
        raise BookingError("Account setup is missing. Run reserve-meals setup first.")
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
    heading(console, "res  /  Couscous Cron", "Webetu meal reservations • Algeria time")
    table = Table(box=box.SIMPLE, show_header=False, pad_edge=False)
    table.add_column("Command", style="bold bright_cyan", no_wrap=True)
    table.add_column("What it does", style="white")
    for command, detail in [
        ("res 3", "Keep the next 3 days booked; run now and keep checking online."),
        ("res until 10-12", "Book through October 12; year is optional."),
        ("res show", "Live table of current and upcoming reservations."),
        ("res plan", "Preview what the standing order would book."),
        ("res log 30", "Past 30 days of reservations and CLI activity."),
        ("res date 10-05", "Book a specific date within the service's 3-day window."),
        ("res sync", "Check and fulfill the current order now."),
        ("res pause / resume", "Pause or resume automatic booking."),
        ("res depots", "Show available restaurants and IDs."),
        ("res doctor", "Show setup, scheduler and recent run health."),
    ]:
        table.add_row(command, detail)
    console.print(table)
    console.print(plain("Breakfast and dinner use the dorm. Lunch uses the main restaurant Sunday–Thursday.", "dim"))


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
            process = subprocess.run(["schtasks", "/Query", "/TN", "Couscous Cron", "/FO", "LIST"],
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
    table.add_row("res on PATH", plain("Yes" if shutil.which("res") else "No", "green" if shutil.which("res") else "yellow"))
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
    if command.isdecimal():
        if len(argv) != 1 or not 1 <= int(command) <= MAX_DAYS:
            raise ValueError("Use res N with a number from 1 to 366.")
        heading(console, f"Reserve the next {int(command)} days", "Rolling order • checking available dates now")
        result = legacy(console, ["order", "days", command])
        if result:
            return result
        append_activity(store, f"Order changed: rolling next {int(command)} day(s).")
        return legacy(console, ["run", "--force"])
    if command == "until":
        if len(argv) != 2:
            raise ValueError("Use res until MM-DD or res until YYYY-MM-DD.")
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
            raise ValueError(f"Use res {command} without extra arguments.")
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
            raise ValueError("Use res log [days], for example res log 30.")
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
            raise ValueError("Use res plan without extra arguments.")
        with store.lock():
            order = store.read("order")
            if not order:
                raise BookingError("No standing order. Use res 3 or res until MM-DD.")
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
            raise ValueError("Use res depots without extra arguments.")
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
            raise ValueError("Use res doctor without extra arguments.")
        heading(console, "Couscous Cron")
        doctor(console, store)
        return 0
    if command in ("sync", "pause", "resume"):
        if len(argv) != 1:
            raise ValueError(f"Use res {command} without extra arguments.")
        heading(console, {"sync": "Checking your order", "pause": "Pause bookings", "resume": "Resume bookings"}[command])
        result = legacy(console, ["run", "--force"] if command == "sync" else ["order", command])
        if not result and command in ("pause", "resume"):
            append_activity(store, f"Automatic booking {command}d.")
        return result
    if command in ("date", "preview"):
        if len(argv) != 2:
            raise ValueError(f"Use res {command} MM-DD.")
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
    raise ValueError("Unknown command. Run res help to see available commands.")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except (ApiError, BookingError, StoreError, ValueError, KeyError, TypeError, OSError) as exc:
        # API failures are already sanitized by Client. Avoid printing raw response data.
        Console(highlight=False).print(plain(f"Error: {exc}", "bold red"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
