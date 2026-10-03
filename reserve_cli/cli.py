import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import uuid
from zoneinfo import ZoneInfo

from dotenv import dotenv_values

from .api import ApiError, Client
from .booking import (BOOKING_WINDOW_DAYS, BookingError, apply_plan, make_plan,
                      meal_number, MEALS, order_dates)
from .store import Store, StoreError
from .paths import default_state_dir


def now_local():
    return datetime.now(ZoneInfo("Africa/Algiers"))


def parser():
    root = argparse.ArgumentParser(prog="reserve-meals", description="Ate: personal meal reservations.")
    root.add_argument("--state-dir", type=Path, default=default_state_dir())
    commands = root.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup", help="Import credentials and original app into encrypted local storage")
    setup.add_argument("--credentials", type=Path, required=True)
    setup.add_argument("--app", type=Path, required=True)
    setup.add_argument("--dorm-id", type=int, required=True)
    setup.add_argument("--main-id", type=int, required=True)
    credentials = commands.add_parser("credentials", help="Update encrypted login credentials after a password change")
    credentials.add_argument("--file", type=Path, required=True)
    commands.add_parser("depots", help="List restaurants available to this account")
    status = commands.add_parser("status", help="Read current reservations")
    status.add_argument("--date", type=date.fromisoformat)
    reserve = commands.add_parser("reserve", help="Preview one date; --apply submits missing meals")
    reserve.add_argument("--date", type=date.fromisoformat, required=True)
    reserve.add_argument("--apply", action="store_true")
    order = commands.add_parser("order", help="Set the standing order used by the scheduler")
    kinds = order.add_subparsers(dest="kind", required=True)
    days = kinds.add_parser("days", help="Maintain a rolling horizon of the next N days")
    days.add_argument("days", type=int)
    until = kinds.add_parser("until", help="Continue booking through an inclusive end date")
    until.add_argument("until", type=date.fromisoformat)
    kinds.add_parser("show")
    kinds.add_parser("pause")
    kinds.add_parser("resume")
    run = commands.add_parser("run", help="Fulfill the standing order once per Algeria calendar day")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--force", action="store_true", help="Recheck today's order, still skipping existing reservations")
    clear = commands.add_parser("clear-pending", help="Unlock an uncertain attempt after checking the official app")
    clear.add_argument("--date", type=date.fromisoformat, required=True)
    clear.add_argument("--meal", choices=list(MEALS.values()), required=True)
    clear.add_argument("--confirmed-absent", action="store_true", required=True)
    return root


def display_plan(plan, emit):
    for item in plan:
        state = f"already booked #{item.existing_id}" if item.existing_id else "to reserve"
        name = item.depot.get("nameFR") or item.depot.get("nameAR")
        emit(f"{item.day}  {item.label:9}  {name}  [{state}]")


def execute(args, store, emit):
    today = now_local().date()
    if args.command == "setup":
        from .import_app import import_signing_key
        existing = store.read("profile")
        if existing:
            raise BookingError("This state directory is already configured. Use a different --state-dir for another account.")
        credentials = dotenv_values(args.credentials, encoding="utf-8-sig", interpolate=False)
        if not credentials.get("student") or not credentials.get("password"):
            raise BookingError("The credentials file must contain student= and password=.")
        if args.dorm_id < 1 or args.main_id < 1:
            raise BookingError("Restaurant IDs must be positive integers.")
        key, fingerprint = import_signing_key(args.app)
        store.write("profile", {"student": credentials["student"], "password": credentials["password"],
                                "dorm_id": args.dorm_id, "main_id": args.main_id,
                                "signing_key": key, "app_sha256": fingerprint})
        emit("Setup complete. Credentials are encrypted for your Windows user; source files were left in place.")
        return
    profile = store.read("profile")
    if not profile:
        raise BookingError("Run setup first.")
    if args.command == "credentials":
        credentials = dotenv_values(args.file, encoding="utf-8-sig", interpolate=False)
        if credentials.get("student") != profile["student"]:
            raise BookingError("Use a separate --state-dir for a different account.")
        if not credentials.get("password"):
            raise BookingError("The file must contain a password.")
        profile["password"] = credentials["password"]
        store.write("profile", profile)
        store.write("run_state", {})
        emit("Encrypted credentials updated; scheduler retries are enabled again.")
        return
    if args.command == "order":
        order = store.read("order")
        if args.kind == "show":
            emit(json.dumps(order or {"status": "not configured"}, ensure_ascii=False))
            return
        if args.kind in ("pause", "resume"):
            if not order:
                raise BookingError("No standing order is configured.")
            order["paused"] = args.kind == "pause"
        elif args.kind == "days":
            if not 1 <= args.days <= 366:
                raise BookingError("Choose between 1 and 366 days.")
            order = {"kind": "days", "days": args.days, "paused": False}
        else:
            if not today < args.until <= today + timedelta(days=366):
                raise BookingError("The end date must be within the next 366 days.")
            order = {"kind": "until", "until": args.until.isoformat(), "paused": False}
        order["revision"] = str(uuid.uuid4())
        store.write("order", order)
        store.write("run_state", {})
        emit("Standing order saved. The scheduler will apply it at its next online check.")
        return
    if args.command == "clear-pending":
        number = next(n for n, name in MEALS.items() if name == args.meal)
        journal = store.read("journal", {})
        key = f"{args.date}:{number}"
        if journal.get(key, {}).get("state") != "pending":
            raise BookingError("There is no pending attempt for that date and meal.")
        journal.pop(key)
        store.write("journal", journal)
        store.write("run_state", {})
        emit("Pending attempt cleared on your confirmation. Future runs will check the server before submitting.")
        return
    order = None
    if args.command == "run":
        order = store.read("order")
        if not order or order.get("paused"):
            emit("Standing order is missing or paused; nothing to do.")
            return
        days, deferred = order_dates(order, today)
        if not days:
            emit("Standing order has ended; nothing to do.")
            return
        state = store.read("run_state", {})
        if not args.force and not args.dry_run and state.get("revision") == order["revision"]:
            if state.get("completed") == today.isoformat():
                return
            if state.get("authentication_blocked"):
                return
            if state.get("retry_after") and datetime.now(timezone.utc) < datetime.fromisoformat(state["retry_after"]):
                return
    elif args.command == "reserve":
        if not today < args.date <= today + timedelta(days=BOOKING_WINDOW_DAYS):
            raise BookingError("Choose tomorrow through three days ahead, matching the original app. "
                               "Use 'order until YYYY-MM-DD' to queue a later date.")
        days = [args.date]
    client = Client(profile)
    try:
        client.login()
        if args.command == "depots":
            for depot in client.depots():
                meals = ", ".join(name for name in MEALS.values() if depot.get(name))
                emit(f"{depot['id']}  {depot['nameFR']}  ({meals})")
            return
        rows = client.reservations()
        if args.command == "status":
            for row in rows:
                if args.date and row.get("date_reserve") != args.date.isoformat():
                    continue
                emit(f"{row['date_reserve']}  {MEALS[meal_number(row)]:9}  {row['depot_fr']}  #{row['id']}")
            return
        plan = make_plan(days, profile, client.depots(), rows)
        display_plan(plan, emit)
        if args.command == "reserve" and not args.apply or args.command == "run" and args.dry_run:
            emit("Preview only; no reservations submitted.")
            return
        apply_plan(client, store, plan, emit)
        if order:
            store.write("run_state", {"revision": order["revision"], "completed": today.isoformat()})
            if deferred:
                emit(f"{deferred} later day(s) will be handled as the three-day booking window opens.")
    finally:
        client.close()


def main(argv=None):
    # Arabic restaurant names should work in Windows Terminal and redirected logs.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parser().parse_args(argv)
    store = Store(args.state_dir)
    def emit(message):
        print(message)
        if args.command == "run":
            with (store.directory / "runs.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"at": now_local().isoformat(), "message": message}, ensure_ascii=False) + "\n")
    try:
        with store.lock():
            try:
                execute(args, store, emit)
            except (ApiError, BookingError) as exc:
                if args.command == "run" and not args.dry_run:
                    order = store.read("order", {})
                    state = store.read("run_state", {})
                    failures = state.get("failures", 0) + 1
                    delay = min(3600, 300 * 2 ** min(failures - 1, 4))
                    store.write("run_state", {"revision": order.get("revision"), "failures": failures,
                                              "authentication_blocked": isinstance(exc, ApiError) and exc.status in (401, 403),
                                              "retry_after": (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()})
                raise exc
    except (ApiError, BookingError, StoreError) as exc:
        emit(f"Error: {exc}")
        return 1
    except (ValueError, KeyError, TypeError, OSError):
        # Do not leak account response values, tokens in URLs, or credentials in tracebacks.
        emit("Error: local configuration or service data could not be processed; no automatic retry was made.")
        return 1
    return 0
