"""Telegram chat commands: the same actions as the terminal, with short plain replies."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
import io

from . import cli
from .api import ApiError, Client
from .booking import BookingError, MEALS, make_plan, meal_number, order_dates
from .config import interval_label, interval_minutes, parse_interval, set_interval
from .short import MAX_DAYS, append_activity, fetch_bookings, local_now, order_text, parse_day, read_activity
from .store import Store, StoreError

COMMANDS = [
    ("status", "Upcoming meals and booking health"),
    ("today", "Today's meals"),
    ("plan", "What the next check would book"),
    ("sync", "Check and book now"),
    ("log", "Recent activity, for example /log 3"),
    ("date", "Book one date, for example /date 11-20"),
    ("days", "Keep the next N days booked, for example /days 5"),
    ("until", "Book through a date, for example /until 12-20"),
    ("pause", "Pause automatic booking"),
    ("resume", "Resume automatic booking"),
    ("interval", "Set the check interval, for example /interval 15m"),
    ("config", "Show settings"),
    ("depots", "List restaurants and IDs"),
    ("doctor", "Health check"),
    ("help", "List commands"),
]
AUTH_REPLY = ("Signing in needs your university password, so it stays out of chat. "
              "Run 'ate auth' on the server, then send /doctor.")


def day_label(day) -> str:
    return day.strftime("%a %d %b")


def meals_by_day(rows) -> dict:
    grouped: dict = {}
    for row in sorted(rows, key=lambda r: (r["date_reserve"], meal_number(r))):
        grouped.setdefault(row["date_reserve"], []).append(MEALS[meal_number(row)])
    return grouped


def run_cli(state_dir, arguments: list[str]) -> tuple[int, list[str]]:
    output = io.StringIO()
    try:
        with redirect_stdout(output):
            code = cli.main(["--state-dir", str(state_dir), *arguments])
    except SystemExit:
        code = 2
    return code, [line.strip() for line in output.getvalue().splitlines() if line.strip()]


def summarise(code: int, lines: list[str]) -> str:
    confirmed = [line.removeprefix("Confirmed: ").rstrip(".") for line in lines if line.startswith("Confirmed:")]
    already = sum(line.startswith("Already reserved:") for line in lines)
    errors = [line.removeprefix("Error: ") for line in lines if line.startswith("Error:")]
    notes = [line for line in lines if "later day(s)" in line or line.startswith("Standing order")]
    parts = []
    if confirmed:
        parts.append(f"Booked {len(confirmed)} meal(s):\n" + "\n".join(confirmed))
    elif not errors:
        parts.append(f"Nothing new to book. {already} meal(s) already reserved." if already
                     else "Nothing to book right now.")
    if errors:
        parts.append("Problem: " + " ".join(errors))
    parts.extend(notes)
    return "\n".join(parts)


class Commands:
    def __init__(self, store: Store):
        self.store = store

    def handle(self, text: str) -> str:
        words = text.strip().split()
        if not words or not words[0].startswith("/"):
            return "Send /help to see what I can do."
        name = words[0][1:].split("@")[0].lower()
        arguments = words[1:]
        handler = {
            "start": self.help, "help": self.help, "status": self.status, "show": self.status,
            "today": self.today, "plan": self.plan, "sync": self.sync, "log": self.log,
            "date": self.date, "days": self.days, "until": self.until, "pause": self.pause,
            "resume": self.resume, "interval": self.interval, "config": self.config,
            "depots": self.depots, "doctor": self.doctor, "auth": self.auth,
        }.get(name)
        if handler is None:
            return "I don't know that command. Send /help."
        try:
            return handler(arguments)
        except (ApiError, BookingError, StoreError, ValueError) as exc:
            return f"Problem: {exc}"
        except Exception:
            return "Something went wrong on the server; check its log."

    def help(self, _arguments) -> str:
        return "Ate commands:\n" + "\n".join(f"/{name} - {detail}" for name, detail in COMMANDS)

    def auth(self, _arguments) -> str:
        return AUTH_REPLY

    def health_line(self) -> str:
        state = self.store.read("run_state", {})
        if state.get("authentication_blocked"):
            return "Booking is SUSPENDED: the login was rejected. " + AUTH_REPLY
        if state.get("failures"):
            return f"Last run failed ({state.get('last_error', 'unknown error')}); retrying."
        done = state.get("completed")
        return f"Booking is healthy. Last full check: {done}." if done else "Booking is healthy."

    def upcoming(self, only_today: bool) -> str:
        today = local_now().date().isoformat()
        with self.store.lock():
            rows, cached_at = fetch_bookings(self.store)
        rows = [r for r in rows if r["date_reserve"] == today] if only_today else \
            [r for r in rows if r["date_reserve"] >= today]
        if not rows:
            return "No meals today." if only_today else "No upcoming meals booked."
        lines = [f"{day_label(date.fromisoformat(day))}: {', '.join(meals)}"
                 for day, meals in meals_by_day(rows).items()]
        if cached_at:
            lines.append(f"(offline view from {cached_at[:16].replace('T', ' ')})")
        return "\n".join(lines)

    def status(self, _arguments) -> str:
        order = self.store.read("order")
        header = f"{order_text(order, local_now().date())}\n{self.health_line()}"
        return header + "\n\n" + self.upcoming(False)

    def today(self, _arguments) -> str:
        return self.upcoming(True)

    def plan(self, _arguments) -> str:
        today = local_now().date()
        with self.store.lock():
            order = self.store.read("order")
            profile = self.store.read("profile")
            if not order or not profile:
                raise BookingError("No standing order yet. Use /days 3.")
            days, deferred = order_dates(order, today)
            client = Client(profile)
            try:
                client.login()
                plan = make_plan(days, profile, client.depots(), client.reservations())
            finally:
                client.close()
        if not plan:
            return "Nothing within the current booking window."
        missing = [item for item in plan if not item.existing_id]
        lines = [f"{len(plan)} meal(s) in the window: {len(plan) - len(missing)} booked, {len(missing)} to book."]
        by_day: dict = {}
        for item in missing:
            by_day.setdefault(item.day, []).append(item.label)
        lines += [f"{day_label(day)}: {', '.join(labels)}" for day, labels in by_day.items()]
        if deferred:
            lines.append(f"{deferred} later day(s) wait for the 3-day window.")
        return "\n".join(lines)

    def sync(self, _arguments) -> str:
        return summarise(*run_cli(self.store.directory, ["run", "--force"]))

    def log(self, arguments) -> str:
        days = int(arguments[0]) if arguments and arguments[0].isdecimal() else 2
        if not 1 <= days <= MAX_DAYS:
            raise ValueError("Choose 1 to 366 days.")
        events = read_activity(self.store.directory / "runs.jsonl", local_now().date() - timedelta(days=days - 1))
        if not events:
            return f"No activity in the last {days} day(s)."
        lines = [f"{datetime.fromisoformat(e['at']).strftime('%d %b %H:%M')}  {e['message'][:110]}"
                 for e in events[-12:]]
        return f"Last {len(lines)} event(s):\n" + "\n".join(lines)

    def date(self, arguments) -> str:
        if len(arguments) != 1:
            raise ValueError("Use /date MM-DD, for example /date 11-20.")
        target = parse_day(arguments[0], local_now().date())
        code, lines = run_cli(self.store.directory, ["reserve", "--date", target.isoformat(), "--apply"])
        append_activity(self.store, f"Manual booking requested for {target.isoformat()} from Telegram: "
                                    + ("completed" if code == 0 else "check result"))
        return summarise(code, lines)

    def days(self, arguments) -> str:
        if len(arguments) != 1 or not arguments[0].isdecimal() or not 1 <= int(arguments[0]) <= MAX_DAYS:
            raise ValueError(f"Use /days N with N from 1 to {MAX_DAYS}.")
        return self.change_order(["order", "days", arguments[0]], f"Order changed: rolling next {arguments[0]} day(s).")

    def until(self, arguments) -> str:
        if len(arguments) != 1:
            raise ValueError("Use /until MM-DD, for example /until 12-20.")
        target = parse_day(arguments[0], local_now().date())
        if not local_now().date() < target <= local_now().date() + timedelta(days=MAX_DAYS):
            raise ValueError("Choose a future date within the next 366 days.")
        return self.change_order(["order", "until", target.isoformat()], f"Order changed: through {target.isoformat()}.")

    def change_order(self, arguments: list[str], note: str) -> str:
        code, lines = run_cli(self.store.directory, arguments)
        if code:
            return summarise(code, lines)
        append_activity(self.store, note + " (from Telegram)")
        return note + "\n" + summarise(*run_cli(self.store.directory, ["run", "--force"]))

    def pause(self, _arguments) -> str:
        return self.toggle("pause")

    def resume(self, _arguments) -> str:
        return self.toggle("resume")

    def toggle(self, action: str) -> str:
        code, lines = run_cli(self.store.directory, ["order", action])
        if code:
            return summarise(code, lines)
        append_activity(self.store, f"Automatic booking {action}d from Telegram.")
        return f"Automatic booking {action}d."

    def interval(self, arguments) -> str:
        if len(arguments) != 1:
            raise ValueError("Use /interval 15m, 2h or 1d.")
        minutes = parse_interval(arguments[0])
        set_interval(self.store, minutes)
        return f"Check interval set to {interval_label(minutes)}. It applies from the next cycle."

    def config(self, _arguments) -> str:
        profile = self.store.read("profile") or {}
        return "\n".join([
            f"Check interval: {interval_label(interval_minutes(self.store))}",
            f"Order: {order_text(self.store.read('order'), local_now().date())}",
            f"Dorm ID: {profile.get('dorm_id', 'not set')}",
            f"Main restaurant ID: {profile.get('main_id', 'not set')}",
        ])

    def depots(self, _arguments) -> str:
        profile = self.store.read("profile")
        if not profile:
            raise BookingError("Account setup is missing. Run 'ate auth' on the server.")
        client = Client(profile)
        try:
            client.login()
            depots = client.depots()
        finally:
            client.close()
        return "\n".join(f"{d['id']}  {d.get('nameFR') or d.get('nameAR')}" for d in depots)

    def doctor(self, _arguments) -> str:
        state = self.store.read("run_state", {})
        lines = [
            f"Account: {'configured' if self.store.read('profile') else 'setup needed'}",
            f"Order: {order_text(self.store.read('order'), local_now().date())}",
            f"Check interval: {interval_label(interval_minutes(self.store))}",
            f"Automatic login: {'SUSPENDED' if state.get('authentication_blocked') else 'ready'}",
            f"Last full check: {state.get('completed', 'none yet')}",
        ]
        if state.get("last_error"):
            lines.append(f"Last error: {state['last_error']}")
        return "\n".join(lines)
