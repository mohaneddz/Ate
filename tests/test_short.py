from datetime import date, datetime
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from rich.console import Console

from reserve_cli.api import ApiError
from reserve_cli.paths import default_state_dir
from reserve_cli.short import (bookings_table, fetch_bookings, legacy, parse_day,
                               setup_wizard,
                               read_activity, run)
from reserve_cli.store import Store


class ShortCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.output = io.StringIO()
        self.console = Console(file=self.output, width=100, force_terminal=True, color_system="truecolor")

    def test_frozen_executable_uses_stable_user_state_folder(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name}):
            self.assertEqual(default_state_dir(), Path(self.temp.name) / "CouscousCron" / "state")

    def test_yearless_date_uses_next_occurrence(self):
        self.assertEqual(parse_day("10-05", date(2026, 10, 3)), date(2026, 10, 5))
        self.assertEqual(parse_day("10-01", date(2026, 10, 3)), date(2027, 10, 1))
        self.assertEqual(parse_day("02-29", date(2027, 3, 1)), date(2028, 2, 29))
        self.assertEqual(parse_day("2026-10-05", date(2026, 10, 3)), date(2026, 10, 5))

    def test_bad_date_has_a_clear_error(self):
        for bad in ("13-01", "10/05", "2026-02-30", "tomorrow"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_day(bad, date(2026, 10, 3))

    @patch("reserve_cli.short.local_now", return_value=datetime(2026, 10, 3, 20, tzinfo=ZoneInfo("Africa/Algiers")))
    def test_short_days_saves_order_then_runs(self, _):
        with patch("reserve_cli.short.legacy", side_effect=[0, 0]) as legacy:
            self.assertEqual(run(["3"], self.console, self.store), 0)
        self.assertEqual([c.args[1] for c in legacy.call_args_list],
                         [["order", "days", "3"], ["run", "--force"]])
        self.assertEqual(len(read_activity(self.store.directory / "runs.jsonl", date(2026, 10, 3))), 1)

    @patch("reserve_cli.short.local_now", return_value=datetime(2026, 10, 3, 20, tzinfo=ZoneInfo("Africa/Algiers")))
    def test_until_expands_year_before_ordering(self, _):
        with patch("reserve_cli.short.legacy", side_effect=[0, 0]) as legacy:
            self.assertEqual(run(["until", "10-05"], self.console, self.store), 0)
        self.assertEqual(legacy.call_args_list[0].args[1], ["order", "until", "2026-10-05"])

    def test_activity_omits_duplicate_preview_rows(self):
        path = self.store.directory / "runs.jsonl"
        entries = [
            {"at": "2026-10-03T19:00:00+01:00", "message": "2026-10-05  lunch Main [already booked]"},
            {"at": "2026-10-03T19:00:01+01:00", "message": "Already reserved: 2026-10-05 lunch (#123)."},
            {"at": "2026-09-01T19:00:01+01:00", "message": "Error: old"},
        ]
        path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
        self.assertEqual([e["message"] for e in read_activity(path, date(2026, 9, 4))],
                         ["Already reserved: 2026-10-05 lunch (#123)."])

    def test_styled_table_displays_untrusted_restaurant_as_plain_text(self):
        row = {"date_reserve": "2026-10-05", "mealtype_fr": "Dîner", "depot_fr": "[red]Cafe[/red]", "id": 123}
        self.console.print(bookings_table([row], title="Bookings"))
        rendered = self.output.getvalue()
        self.assertIn("[red]Cafe[/red]", rendered)
        self.assertIn("\x1b[", rendered)

    def test_action_output_collects_preview_into_one_table(self):
        sample = ("2026-10-05  breakfast  Dorm  [already booked #123]\n"
                  "2026-10-05  lunch      Main  [to reserve]\n"
                  "Confirmed: 2026-10-05 lunch (#124).\n")
        with patch("reserve_cli.short.cli.main", side_effect=lambda _: (print(sample, end=""), 0)[1]):
            self.assertEqual(legacy(self.console, ["run"]), 0)
        output = self.output.getvalue()
        self.assertIn("Booking check", output)
        self.assertIn("To reserve", output)
        self.assertIn("Confirmed:", output)
        self.assertNotIn("[to reserve]", output)

    def test_offline_show_uses_encrypted_snapshot(self):
        self.store.write("profile", {"student": "fake"})
        rows = [{"date_reserve": "2026-10-05", "mealtype_fr": "Dîner", "depot_fr": "Dorm", "id": 123}]
        self.store.write("reservation_cache", {"at": "2026-10-03T18:00:00+01:00", "rows": rows})
        with patch("reserve_cli.short.Client") as client:
            client.return_value.login.side_effect = ApiError("Offline")
            result, cached = fetch_bookings(self.store)
        self.assertEqual(result, rows)
        self.assertEqual(cached, "2026-10-03T18:00:00+01:00")

    def test_setup_wizard_saves_only_encrypted_account_data(self):
        app = Path(self.temp.name) / "original.xapk"
        app.write_bytes(b"fake fixture")
        replies = iter([str(app), "test-student", "10", "20", "3"])
        self.console.input = lambda _: next(replies)
        depots = [
            {"id": 10, "nameFR": "Dorm", "breakfast": True, "lunch": True, "dinner": True},
            {"id": 20, "nameFR": "Main", "breakfast": False, "lunch": True, "dinner": False},
        ]
        with patch("reserve_cli.import_app.import_signing_key", return_value=("test-key", "a" * 64)), \
             patch("reserve_cli.short.getpass.getpass", return_value="private-test-password"), \
             patch("reserve_cli.short.Client") as client:
            client.return_value.depots.return_value = depots
            self.assertEqual(setup_wizard(self.console, self.store), 0)
        profile = self.store.read("profile")
        self.assertEqual((profile["dorm_id"], profile["main_id"]), (10, 20))
        self.assertEqual(self.store.read("order")["days"], 3)
        self.assertNotIn(b"private-test-password", (self.store.directory / "profile.bin").read_bytes())
        self.assertNotIn("private-test-password", self.output.getvalue())

    def test_check_app_uses_local_file_without_credentials(self):
        app = Path(self.temp.name) / "webetu.xapk"
        app.write_bytes(b"test fixture")
        with patch("reserve_cli.import_app.import_signing_key", return_value=("test-key", "b" * 64)) as importer:
            self.assertEqual(run(["check-app", str(app)], self.console, self.store), 0)
        importer.assert_called_once_with(app)
        self.assertNotIn("test-key", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
