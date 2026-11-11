from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from reserve_cli.api import ApiError
from reserve_cli.botcommands import AUTH_REPLY, COMMANDS, Commands, summarise
from reserve_cli.serve import handle_update, serve
from reserve_cli.store import Store

PROFILE = {"student": "test-student", "password": "test-password", "dorm_id": 10, "main_id": 20,
           "signing_key": "test-only-key"}
DEPOTS = [
    {"id": 10, "nameFR": "Dorm", "nameAR": "إقامة", "breakfast": True, "lunch": True, "dinner": True},
    {"id": 20, "nameFR": "Main", "nameAR": "مطعم", "breakfast": False, "lunch": True, "dinner": False},
]
NOW = datetime(2026, 11, 11, 9, tzinfo=ZoneInfo("Africa/Algiers"))
TELEGRAM = {"token": "123456789:AAExampleTokenForTestsOnly_0123456789abc", "chat_id": 42, "name": "Mohaned"}


def booking(day, meal, label):
    return {"id": hash((day, meal)) % 1000, "date_reserve": day, "mealtype_fr": label, "depot_fr": "Dorm"}


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name))
        self.store.write("profile", PROFILE)
        self.store.write("order", {"kind": "days", "days": 3, "revision": "one"})
        self.commands = Commands(self.store)
        for target in ("reserve_cli.botcommands.local_now", "reserve_cli.short.local_now"):
            patcher = patch(target, return_value=NOW)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_help_lists_every_command_and_each_one_is_handled(self):
        text = self.commands.handle("/help")
        for name, _ in COMMANDS:
            self.assertIn(f"/{name}", text)
            self.assertNotIn("don't know", self.handled(name))

    def handled(self, name):
        # Replace work with a stub so only routing is checked.
        stub = Mock(return_value="routed")
        with patch.object(Commands, name if name not in ("help",) else "help", stub, create=True), \
                patch.object(Commands, "show", stub, create=True):
            return self.commands.handle(f"/{name}")

    def test_unknown_and_plain_text_get_a_hint(self):
        self.assertIn("/help", self.commands.handle("hello"))
        self.assertIn("don't know", self.commands.handle("/nonsense"))

    def test_auth_is_refused_in_chat(self):
        self.assertEqual(self.commands.handle("/auth"), AUTH_REPLY)

    def test_command_suffix_for_groups_is_accepted(self):
        self.assertIn("Ate commands", self.commands.handle("/help@ate_cli_bot"))

    def test_status_shows_health_and_meals_by_day(self):
        rows = [booking("2026-11-12", 1, "Petit-déjeuner"), booking("2026-11-12", 3, "Dîner"),
                booking("2026-11-10", 1, "Petit-déjeuner")]
        with patch("reserve_cli.botcommands.fetch_bookings", return_value=(rows, None)):
            text = self.commands.handle("/status")
        self.assertIn("✅ Healthy · 3d rolling", text)
        self.assertIn("Thu 12 Nov  🍳🌙", text)
        self.assertNotIn("10 Nov", text)

    def test_status_warns_when_suspended_and_how_to_fix(self):
        self.store.write("run_state", {"authentication_blocked": True})
        with patch("reserve_cli.botcommands.fetch_bookings", return_value=([], None)):
            text = self.commands.handle("/status")
        self.assertIn("Suspended", text)
        self.assertIn("ate auth", text)

    def test_plan_counts_booked_and_missing_meals(self):
        client = Mock()
        client.depots.return_value = DEPOTS
        client.reservations.return_value = []
        with patch("reserve_cli.botcommands.Client", return_value=client):
            text = self.commands.handle("/plan")
        self.assertIn("9 meal(s) in the window: ✅ 0 booked, ⏳ 9 to book", text)
        self.assertIn("12–14 Nov", text)
        client.close.assert_called_once()

    def test_sync_summarises_the_run(self):
        lines = ["Already reserved: 2026-11-12 breakfast (#1).", "Confirmed: 2026-11-12 dinner (#5)."]
        with patch("reserve_cli.botcommands.run_cli", return_value=(0, lines)) as run_cli:
            text = self.commands.handle("/sync")
        self.assertEqual(run_cli.call_args.args[1], ["run", "--force"])
        self.assertIn("✅ Booked 1 meal", text)
        self.assertIn("🌙", text)

    def test_order_commands_validate_before_touching_anything(self):
        with patch("reserve_cli.botcommands.run_cli") as run_cli:
            self.assertIn("Use /days N", self.commands.handle("/days zero"))
            self.assertIn("Use /days N", self.commands.handle("/days 900"))
            self.assertIn("Use /date MM-DD", self.commands.handle("/date"))
        run_cli.assert_not_called()

    def test_days_sets_the_order_then_checks_now(self):
        with patch("reserve_cli.botcommands.run_cli", return_value=(0, [])) as run_cli:
            text = self.commands.handle("/days 5")
        self.assertEqual([call.args[1] for call in run_cli.call_args_list],
                         [["order", "days", "5"], ["run", "--force"]])
        self.assertIn("rolling next 5 day(s)", text)

    def test_pause_and_resume(self):
        with patch("reserve_cli.botcommands.run_cli", return_value=(0, [])) as run_cli:
            self.assertEqual(self.commands.handle("/pause"), "⏸️ Automatic booking paused.")
            self.assertEqual(self.commands.handle("/resume"), "▶️ Automatic booking resumed.")
        self.assertEqual([call.args[1] for call in run_cli.call_args_list], [["order", "pause"], ["order", "resume"]])

    def test_log_shows_recent_events_only(self):
        path = Path(self.temporary.name) / "runs.jsonl"
        path.write_text('{"at": "2026-11-11T08:00:00+01:00", "message": "Confirmed: 2026-11-12 dinner (#5)."}\n'
                        '{"at": "2026-10-01T08:00:00+01:00", "message": "old event"}\n'
                        '{"at": "2026-11-11T08:05:00+01:00", "message": "Already reserved: 2026-11-12 lunch (#6)."}\n',
                        encoding="utf-8")
        text = self.commands.handle("/log")
        self.assertIn("Confirmed: 2026-11-12 dinner", text)
        self.assertNotIn("old event", text)
        self.assertNotIn("Already reserved", text)

    def test_service_errors_become_short_problems_and_unknown_ones_leak_nothing(self):
        with patch("reserve_cli.botcommands.fetch_bookings", side_effect=ApiError("The meal service returned HTTP 500.")):
            self.assertEqual(self.commands.handle("/today"), "⚠️ Problem: The meal service returned HTTP 500.")
        with patch("reserve_cli.botcommands.fetch_bookings", side_effect=RuntimeError("secret detail")):
            self.assertNotIn("secret", self.commands.handle("/today"))

    def test_config_hides_the_student_number(self):
        text = self.commands.handle("/config")
        self.assertIn("Dorm ID: 10", text)
        self.assertNotIn("test-student", text)
        self.assertNotIn("test-password", text)

    def test_summarise_cases(self):
        self.assertIn("Nothing to book", summarise(0, []))
        self.assertIn("2 meal(s) already", summarise(0, ["Already reserved: a (#1).", "Already reserved: b (#2)."]))
        self.assertIn("⚠️ Problem: boom", summarise(1, ["Error: boom"]))


class ServeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name))
        self.store.write("telegram", TELEGRAM)

    def message(self, chat_id, text, kind="private"):
        return {"update_id": 7, "message": {"chat": {"id": chat_id, "type": kind}, "text": text}}

    def test_only_the_paired_private_chat_is_answered(self):
        bot, commands = Mock(), Mock()
        commands.handle.return_value = "reply"
        for update in (self.message(99, "/sync"), self.message(42, "/sync", "group")):
            handle_update(update, TELEGRAM, commands, bot)
        bot.send.assert_not_called()
        handle_update(self.message(42, "/help"), TELEGRAM, commands, bot)
        bot.send.assert_called_once_with(42, "reply")

    def test_loop_checks_bookings_publishes_menu_and_answers(self):
        bot = Mock()
        bot.updates.return_value = [self.message(42, "/help")]
        with patch("reserve_cli.serve.cli.main", return_value=0) as booking_check:
            serve(self.store, cycles=1, clock=lambda: 0, sleep=lambda _: None, bot_factory=lambda _: bot)
        self.assertEqual(booking_check.call_args.args[0][-1], "run")
        self.assertEqual(bot.call.call_args.args[0], "setMyCommands")
        self.assertIn("Ate commands", bot.send.call_args.args[1])

    def test_without_telegram_it_still_runs_checks(self):
        self.store.delete("telegram")
        pauses = []
        with patch("reserve_cli.serve.cli.main", return_value=0) as booking_check:
            serve(self.store, cycles=1, clock=lambda: 0, sleep=pauses.append)
        booking_check.assert_called_once()
        self.assertEqual(len(pauses), 1)

    def test_a_telegram_outage_does_not_stop_the_loop(self):
        from reserve_cli.telegram import TelegramError
        bot = Mock()
        bot.updates.side_effect = TelegramError("Could not reach Telegram.")
        pauses = []
        with patch("reserve_cli.serve.cli.main", return_value=0):
            serve(self.store, cycles=2, clock=lambda: 0, sleep=pauses.append, bot_factory=lambda _: bot)
        self.assertEqual(len(pauses), 2)


if __name__ == "__main__":
    unittest.main()
