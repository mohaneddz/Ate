from datetime import date, datetime
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import requests

from reserve_cli.api import ApiError, Client, compact_json, signed_headers
from reserve_cli.booking import (BookingError, apply_plan, make_plan, order_dates)
from reserve_cli.cli import execute, parser
from reserve_cli.store import Store, StoreError

MONDAY = date(2026, 10, 5)
PROFILE = {"dorm_id": 10, "main_id": 20, "signing_key": "test-only-key"}
DEPOTS = [
    {"id": 10, "nameFR": "Dorm", "nameAR": "إقامة", "breakfast": True, "lunch": True, "dinner": True},
    {"id": 20, "nameFR": "Main", "nameAR": "مطعم", "breakfast": False, "lunch": True, "dinner": False},
]
LABELS = {1: "Petit-déjeuner", 2: "Déjeuner", 3: "Dîner"}


def row(meal, day=MONDAY, depot=None):
    return {"id": 100 + meal, "date_reserve": day.isoformat(), "mealtype_fr": LABELS[meal],
            "depot_fr": depot or ("Main" if meal == 2 else "Dorm")}


class MemoryStore:
    def __init__(self):
        self.data = {}

    def read(self, key, default=None):
        import copy
        return copy.deepcopy(self.data.get(key, default))

    def write(self, key, value):
        import copy
        self.data[key] = copy.deepcopy(value)


class FakeClient:
    def __init__(self, rows=None, timeout=False, accepted=True):
        self.rows = list(rows or [])
        self.calls = []
        self.timeout = timeout
        self.accepted = accepted

    def reservations(self):
        return list(self.rows)

    def reserve(self, day, meal, depot):
        self.calls.append((day, meal, depot))
        if self.accepted:
            self.rows.append(row(meal, date.fromisoformat(day)))
        if self.timeout:
            raise ApiError("Simulated lost response")
        return {"success": self.accepted, "data": [{"status": self.accepted}]}


class PlanningTests(unittest.TestCase):
    def test_monday_uses_dorm_main_dorm(self):
        plan = make_plan([MONDAY], PROFILE, DEPOTS, [])
        self.assertEqual([(p.meal, p.depot["id"]) for p in plan], [(1, 10), (2, 20), (3, 10)])

    def test_weekend_has_no_lunch_and_sunday_does(self):
        for day in (date(2026, 10, 9), date(2026, 10, 10)):
            self.assertEqual([p.meal for p in make_plan([day], PROFILE, DEPOTS, [])], [1, 3])
        self.assertEqual(len(make_plan([date(2026, 10, 11)], PROFILE, DEPOTS, [])), 3)

    def test_conflict_stops_whole_plan(self):
        with self.assertRaisesRegex(BookingError, "elsewhere"):
            make_plan([MONDAY], PROFILE, DEPOTS, [row(2, depot="Elsewhere")])

    def test_unknown_meal_fails_closed(self):
        unknown = {**row(1), "mealtype_fr": "new meal code"}
        with self.assertRaisesRegex(BookingError, "unknown meal"):
            make_plan([MONDAY], PROFILE, DEPOTS, [unknown])

    def test_existing_bookings_do_not_submit(self):
        client = FakeClient([row(n) for n in (1, 2, 3)])
        plan = make_plan([MONDAY], PROFILE, DEPOTS, client.rows)
        apply_plan(client, MemoryStore(), plan, lambda _: None)
        self.assertEqual(client.calls, [])

    def test_booking_created_by_phone_after_plan_is_skipped(self):
        plan = make_plan([MONDAY], PROFILE, DEPOTS, [])
        client = FakeClient([row(n) for n in (1, 2, 3)])
        apply_plan(client, MemoryStore(), plan, lambda _: None)
        self.assertEqual(client.calls, [])

    def test_timeout_with_server_confirmation_is_success(self):
        client = FakeClient(timeout=True)
        store = MemoryStore()
        plan = make_plan([MONDAY], PROFILE, DEPOTS, [])[:1]
        apply_plan(client, store, plan, lambda _: None)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(store.read("journal")[plan[0].key]["state"], "confirmed")

    def test_uncertain_submission_cannot_be_repeated(self):
        client = FakeClient(timeout=True, accepted=False)
        store = MemoryStore()
        plan = make_plan([MONDAY], PROFILE, DEPOTS, [])
        with self.assertRaisesRegex(BookingError, "unconfirmed"):
            apply_plan(client, store, plan, lambda _: None)
        with self.assertRaisesRegex(BookingError, "earlier attempt"):
            apply_plan(client, store, plan, lambda _: None)
        self.assertEqual(len(client.calls), 1)

    def test_pending_dinner_blocks_before_breakfast_write(self):
        client, store = FakeClient(), MemoryStore()
        plan = make_plan([MONDAY], PROFILE, DEPOTS, [])
        store.write("journal", {plan[-1].key: {"state": "pending"}})
        with self.assertRaises(BookingError):
            apply_plan(client, store, plan, lambda _: None)
        self.assertEqual(client.calls, [])

    def test_pending_is_reconciled_if_now_visible(self):
        client, store = FakeClient([row(1)]), MemoryStore()
        plan = make_plan([MONDAY], PROFILE, DEPOTS, client.rows)[:1]
        store.write("journal", {plan[0].key: {"state": "pending"}})
        apply_plan(client, store, plan, lambda _: None)
        self.assertEqual(store.read("journal")[plan[0].key]["state"], "confirmed")

    def test_fixed_order_expires_and_long_order_is_deferred(self):
        days, deferred = order_dates({"kind": "until", "until": "2026-10-12"}, date(2026, 10, 3))
        self.assertEqual(days, [date(2026, 10, n) for n in (4, 5, 6)])
        self.assertEqual(deferred, 6)
        self.assertEqual(order_dates({"kind": "until", "until": "2026-10-05"}, MONDAY), ([], 0))

    def test_rolling_order_advances(self):
        self.assertEqual(order_dates({"kind": "days", "days": 2}, MONDAY)[0],
                         [date(2026, 10, 6), date(2026, 10, 7)])


class ProtocolTests(unittest.TestCase):
    def test_details_are_json_strings_and_signed_body_is_sent_verbatim(self):
        client = Client(PROFILE)
        client.context = {"uuid": "test-account", "wilaya": "test-region", "residence": 10, "token": "web-token"}
        client.web_token = "web-token"
        client.meal_token = "meal-token"
        with patch.object(client, "_request", return_value={}) as request:
            client.reserve("2026-10-05", 1, 10)
        args, kwargs = request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[2], "/reservemeal")
        import json
        body = json.loads(kwargs["data"])
        self.assertIsInstance(body["details"][0], str)
        self.assertEqual(json.loads(body["details"][0]), {"date_reserve": "2026-10-05", "menu_type": 1, "idDepot": 10})
        headers = kwargs["headers"]
        self.assertEqual(headers["authorization"], "Bearer meal-token")
        expected = signed_headers("test-only-key", kwargs["data"].decode(), timestamp=headers["X-Timestamp"], nonce=headers["X-Nonce"])
        self.assertEqual(headers["X-Signature"], expected["X-Signature"])

    def test_pagination_uses_known_host_not_next_url(self):
        client = Client(PROFILE)
        client.context, client.web_token = {}, "test"
        pages = [{"data": [row(1)], "links": {"next": "https://untrusted.test/?secret=x"}, "meta": {"current_page": 1}},
                 {"data": [row(2)], "links": {"next": None}, "meta": {"current_page": 2, "total": 2}}]
        with patch.object(client, "_onou", side_effect=pages) as request:
            self.assertEqual(len(client.reservations()), 2)
        self.assertTrue(all(c.args[1] == "/meal-reservations/student" for c in request.call_args_list))
        self.assertEqual(request.call_args_list[-1].kwargs["params"]["page"], 2)

    def test_transport_exception_cannot_leak_sensitive_url(self):
        client = Client(PROFILE)
        with patch.object(client.session, "request", side_effect=requests.Timeout("https://example.test/?token=SECRET")) as send:
            with self.assertRaises(ApiError) as result:
                client._request("GET", "https://gs-api.onou.dz/api", "/getdepotres")
        self.assertNotIn("SECRET", str(result.exception))
        self.assertFalse(send.call_args.kwargs["allow_redirects"])


class SchedulerTests(unittest.TestCase):
    @patch("reserve_cli.cli.now_local", return_value=datetime(2026, 10, 3, 20, tzinfo=ZoneInfo("Africa/Algiers")))
    def test_successful_day_skips_login(self, _):
        store = MemoryStore()
        store.write("profile", PROFILE)
        store.write("order", {"kind": "until", "until": "2026-10-05", "revision": "one"})
        store.write("run_state", {"revision": "one", "completed": "2026-10-03"})
        with patch("reserve_cli.cli.Client") as client:
            execute(parser().parse_args(["run"]), store, lambda _: None)
        client.assert_not_called()

    @patch("reserve_cli.cli.now_local", return_value=datetime(2026, 10, 3, 20, tzinfo=ZoneInfo("Africa/Algiers")))
    def test_authentication_block_skips_login(self, _):
        store = MemoryStore()
        store.write("profile", PROFILE)
        store.write("order", {"kind": "days", "days": 3, "revision": "one"})
        store.write("run_state", {"revision": "one", "authentication_blocked": True})
        with patch("reserve_cli.cli.Client") as client:
            execute(parser().parse_args(["run"]), store, lambda _: None)
        client.assert_not_called()


class StorageTests(unittest.TestCase):
    def test_interrupted_account_commit_recovers_on_next_read(self):
        import base64
        import json
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            original = {"student": "original", "password": "previous"}
            store.write("profile", original)
            old_bytes = (store.directory / "profile.bin").read_bytes()
            # This is the on-disk state left by a process killed after its first write.
            snapshot = {"profile": base64.b64encode(old_bytes).decode("ascii"), "order": None}
            from reserve_cli.store import _protect
            store._replace_bytes("auth-transaction", _protect(json.dumps(snapshot).encode()))
            store.write("profile", {"student": "partial", "password": "new"})
            store.write("order", {"kind": "days", "days": 7})
            restarted = Store(Path(temporary))
            self.assertEqual(restarted.read("profile"), original)
            self.assertIsNone(restarted.read("order"))
            self.assertFalse((store.directory / "auth-transaction.bin").exists())

    def test_account_store_roundtrip_and_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary))
            value = {"password": "not-a-real-secret"}
            with store.lock():
                store.write("test", value)
            if os.name == "nt":
                self.assertNotIn(b"not-a-real-secret", (Path(temporary) / "test.bin").read_bytes())
            else:
                self.assertEqual((Path(temporary) / "test.bin").stat().st_mode & 0o777, 0o600)
                self.assertEqual(Path(temporary).stat().st_mode & 0o777, 0o700)
            self.assertEqual(store.read("test"), value)
            store.append_log('test event')
            if os.name == "posix":
                self.assertEqual((Path(temporary) / "runs.jsonl").stat().st_mode & 0o777, 0o600)

    def test_linux_lock_excludes_another_command(self):
        if os.name != "posix":
            self.skipTest("Linux file locking")
        with tempfile.TemporaryDirectory() as temporary:
            first = Store(Path(temporary))
            second = Store(Path(temporary))
            with first.lock():
                with self.assertRaisesRegex(StoreError, "Another reservation command"):
                    with second.lock():
                        pass
            with second.lock():
                pass


if __name__ == "__main__":
    unittest.main()
