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
from reserve_cli.auth import load_credentials
from reserve_cli.paths import default_state_dir
from reserve_cli.short import (bookings_table, fetch_bookings, legacy, parse_day,
                               auth_wizard,
                               read_activity, run)
from reserve_cli.signing import SIGNING_KEY
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
            self.assertEqual(default_state_dir(), Path(self.temp.name) / "Ate" / "state")

    def test_source_command_uses_same_windows_state_folder(self):
        with patch.object(sys, "frozen", False, create=True), \
             patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name}):
            self.assertEqual(default_state_dir(), Path(self.temp.name) / "Ate" / "state")

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

    def test_auth_wizard_saves_only_encrypted_account_data(self):
        replies = iter(["test-student", "10", "20", "3"])
        self.console.input = lambda _: next(replies)
        depots = [
            {"id": 10, "nameFR": "Dorm", "breakfast": True, "lunch": True, "dinner": True},
            {"id": 20, "nameFR": "Main", "breakfast": False, "lunch": True, "dinner": False},
        ]
        with patch("reserve_cli.short.getpass.getpass", return_value="private-test-password"), \
             patch("reserve_cli.short.Client") as client:
            client.return_value.depots.return_value = depots
            self.assertEqual(auth_wizard(self.console, self.store), 0)
        profile = self.store.read("profile")
        self.assertEqual((profile["dorm_id"], profile["main_id"]), (10, 20))
        self.assertEqual(profile["signing_key"], SIGNING_KEY)
        self.assertEqual(self.store.read("order")["days"], 3)
        self.assertNotIn(b"private-test-password", (self.store.directory / "profile.bin").read_bytes())
        self.assertNotIn("private-test-password", self.output.getvalue())

    def test_auth_file_imports_markdown_values_without_prompting_for_ids(self):
        path = Path(self.temp.name) / "account.md"
        path.write_text("# Account\n| student | test-student |\n| password | private-test-password |\n"
                        "| dorm_id | 10 |\n| main_id | 20 |\n| days | 4 |\n", encoding="utf-8")
        self.console.input = lambda _: self.fail("File supplies all account options")
        depots = [{"id": 10, "nameFR": "Dorm", "breakfast": True, "dinner": True},
                  {"id": 20, "nameFR": "Main", "lunch": True}]
        with patch("reserve_cli.short.Client") as client:
            client.return_value.depots.return_value = depots
            self.assertEqual(run(["auth", str(path)], self.console, self.store), 0)
        self.assertEqual(self.store.read("order")["days"], 4)
        self.assertNotIn("private-test-password", self.output.getvalue())

    def test_reauth_preserves_order_and_failed_login_keeps_old_profile(self):
        self.store.write("profile", {"student": "test-student", "password": "old-password",
                                     "dorm_id": 10, "main_id": 20, "signing_key": SIGNING_KEY})
        order = {"kind": "days", "days": 30, "paused": False, "revision": "existing"}
        self.store.write("order", order)
        path = Path(self.temp.name) / "new.env"
        path.write_text("student=test-student\npassword=new-password\ndorm_id=10\nmain_id=20\n", encoding="utf-8")
        depots = [{"id": 10, "nameFR": "Dorm", "breakfast": True, "dinner": True},
                  {"id": 20, "nameFR": "Main", "lunch": True}]
        with patch("reserve_cli.short.Client") as client:
            client.return_value.login.side_effect = ApiError("Rejected", status=401)
            with self.assertRaises(ApiError):
                auth_wizard(self.console, self.store, path)
            self.assertEqual(self.store.read("profile")["password"], "old-password")
            client.return_value.login.side_effect = None
            client.return_value.depots.return_value = depots
            self.assertEqual(auth_wizard(self.console, self.store, path), 0)
        self.assertEqual(self.store.read("profile")["password"], "new-password")
        self.assertEqual(self.store.read("order"), order)

    def test_reauth_file_keeps_existing_dorm_when_old_name_has_changed(self):
        self.store.write("profile", {"student": "test-student", "password": "old-password",
                                     "dorm_id": 10, "main_id": 20, "signing_key": SIGNING_KEY})
        self.store.write("order", {"kind": "days", "days": 30, "paused": False, "revision": "existing"})
        path = Path(self.temp.name) / "account.env"
        path.write_text("student=test-student\npassword=new-password\n"
                        "dorm_id=Old Dorm Spelling\nmain_id=Main Restaurant\n", encoding="utf-8")
        self.console.input = lambda _: self.fail("Existing restaurant ID should be kept")
        depots = [{"id": 10, "nameFR": "Dorm New Spelling", "breakfast": True, "dinner": True},
                  {"id": 20, "nameFR": "Main Restaurant", "lunch": True}]
        with patch("reserve_cli.short.Client") as client:
            client.return_value.depots.return_value = depots
            self.assertEqual(auth_wizard(self.console, self.store, path), 0)
        self.assertEqual((self.store.read("profile")["dorm_id"], self.store.read("profile")["main_id"]),
                         (10, 20))
        self.assertIn("keeping current ID 10", self.output.getvalue())

    def test_credential_import_rejects_missing_and_conflicting_fields(self):
        path = Path(self.temp.name) / "account.txt"
        path.write_text("student=one\npassword=secret\nstudent=two\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "conflicting student"):
            load_credentials(path)
        path.write_text("student=one\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "student and password"):
            load_credentials(path)
        with self.assertRaisesRegex(ValueError, "Credential file was not found"):
            load_credentials(Path(self.temp.name) / "absent.env")

    def test_credential_import_accepts_json(self):
        path = Path(self.temp.name) / "account.json"
        path.write_text('{"student_id": 1234, "password": "secret"}', encoding="utf-8")
        self.assertEqual(load_credentials(path)["student"], "1234")

    def test_markdown_password_keeps_equals_and_colon_characters(self):
        path = Path(self.temp.name) / "credentials.md"
        path.write_text("- **student**: 1234\n- **password**: `one=two:three`\n", encoding="utf-8")
        self.assertEqual(load_credentials(path)["password"], "one=two:three")


if __name__ == "__main__":
    unittest.main()
