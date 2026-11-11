from datetime import datetime
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests
from rich.console import Console

from reserve_cli.api import ApiError
from reserve_cli.cli import SUSPENDED_NOTICE, main
from reserve_cli.short import doctor, run
from reserve_cli.store import Store
from reserve_cli.telegram import (Notifier, TelegramBot, TelegramError, find_private_chat,
                                  load_bot_token)

TOKEN = "123456789:AAExampleTokenForTestsOnly_0123456789abc"
PROFILE = {"student": "test-student", "password": "test-password", "dorm_id": 10, "main_id": 20,
           "signing_key": "test-only-key"}
NOW = datetime(2026, 11, 11, 9, tzinfo=ZoneInfo("Africa/Algiers"))


class BotFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def write(self, text):
        path = Path(self.temporary.name) / "bot.env"
        path.write_text(text, encoding="utf-8")
        return path

    def test_token_is_read_and_the_link_line_is_ignored(self):
        path = self.write(f"link=https://t.me/ExampleBot\nhttp={TOKEN}\n")
        self.assertEqual(load_bot_token(path), TOKEN)

    def test_bare_token_line_works(self):
        self.assertEqual(load_bot_token(self.write(TOKEN + "\n")), TOKEN)

    def test_file_without_a_token_is_rejected(self):
        with self.assertRaises(TelegramError):
            load_bot_token(self.write("link=https://t.me/ExampleBot\n"))

    def test_malformed_token_is_rejected_without_echoing_it(self):
        with self.assertRaises(TelegramError) as result:
            load_bot_token(self.write("http=not-a-token\n"))
        self.assertNotIn("not-a-token", str(result.exception))


class BotClientTests(unittest.TestCase):
    def test_transport_error_cannot_leak_the_token(self):
        bot = TelegramBot(TOKEN)
        error = requests.Timeout(f"https://api.telegram.org/bot{TOKEN}/getMe timed out")
        with patch.object(bot.session, "post", side_effect=error) as post:
            with self.assertRaises(TelegramError) as result:
                bot.me()
        self.assertNotIn(TOKEN, str(result.exception))
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertTrue(post.call_args.args[0].startswith("https://api.telegram.org/bot"))

    def test_rejected_token_has_a_clear_error(self):
        bot = TelegramBot(TOKEN)
        with patch.object(bot.session, "post", return_value=Mock(status_code=401)):
            with self.assertRaisesRegex(TelegramError, "rejected the bot token"):
                bot.me()

    def test_long_messages_are_cut_to_telegrams_limit(self):
        bot = TelegramBot(TOKEN)
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True, "result": {}}
        with patch.object(bot.session, "post", return_value=response) as post:
            bot.send(1, "x" * 9000)
        self.assertLessEqual(len(post.call_args.kwargs["json"]["text"]), 4096)


class FakeBot:
    def __init__(self, batches):
        self.batches = list(batches)
        self.offsets = []

    def updates(self, offset=None, wait=0):
        self.offsets.append(offset)
        return self.batches.pop(0) if self.batches else []


def private_message(update_id, chat_id=42, name="Mohaned"):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id, "type": "private"},
                                                "from": {"first_name": name, "is_bot": False}}}


class PairingTests(unittest.TestCase):
    def test_groups_and_bots_are_ignored_and_the_private_chat_is_chosen(self):
        group = {"update_id": 1, "message": {"chat": {"id": -5, "type": "group"}, "from": {"first_name": "G"}}}
        robot = {"update_id": 2, "message": {"chat": {"id": 9, "type": "private"},
                                             "from": {"first_name": "B", "is_bot": True}}}
        bot = FakeBot([[group, robot, private_message(3)]])
        self.assertEqual(find_private_chat(bot, seconds=60), {"chat_id": 42, "name": "Mohaned"})
        self.assertEqual(bot.offsets[-1], 4)

    def test_no_message_before_the_deadline_returns_nothing(self):
        ticks = iter([0, 0, 100])
        self.assertIsNone(find_private_chat(FakeBot([[]]), seconds=60, clock=lambda: next(ticks)))


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name))
        self.store.write("profile", PROFILE)
        self.store.write("order", {"kind": "days", "days": 3, "revision": "one"})

    def scheduled(self, *arguments, execute_effect=None, error=None):
        sent = []
        patches = [patch("reserve_cli.cli.now_local", return_value=NOW),
                   patch("reserve_cli.cli.Notifier.deliver", lambda _self, messages, log=None: sent.extend(messages))]
        if error:
            patches.append(patch("reserve_cli.cli.Client", **{"return_value.login.side_effect": error}))
        else:
            patches.append(patch("reserve_cli.cli.execute", side_effect=execute_effect))
        for item in patches:
            item.start()
        try:
            main(["--state-dir", self.temporary.name, *arguments])
        finally:
            for item in patches:
                item.stop()
        return sent

    def rejected(self):
        return ApiError("The university login returned HTTP 401; response content withheld.", 401, "university login")

    def test_booked_meals_are_summarised_in_one_message(self):
        def book(args, store, emit):
            emit("Confirmed: 2026-11-12 breakfast (#1).")
            emit("Confirmed: 2026-11-12 dinner (#2).")
            self.store.write("run_state", {"revision": "one", "completed": "2026-11-11"})
        sent = self.scheduled("run", execute_effect=book)
        self.assertEqual(len(sent), 1)
        self.assertIn("Booked 2 meal(s)", sent[0])
        self.assertIn("2026-11-12 dinner (#2)", sent[0])

    def test_nothing_new_sends_nothing(self):
        self.assertEqual(self.scheduled("run", execute_effect=lambda *_: None), [])

    def test_manual_force_and_dry_run_never_alert(self):
        def book(args, store, emit):
            emit("Confirmed: 2026-11-12 breakfast (#1).")
        self.assertEqual(self.scheduled("run", "--force", execute_effect=book), [])
        self.assertEqual(self.scheduled("run", "--dry-run", execute_effect=book), [])

    def test_only_the_first_failure_in_a_streak_alerts(self):
        first = self.scheduled("run", error=ApiError("The meal service returned HTTP 500.", 500, "meal service"))
        self.assertEqual(len(first), 1)
        self.assertIn("Booking problem", first[0])
        state = self.store.read("run_state")
        state["retry_after"] = "2000-01-01T00:00:00+00:00"
        self.store.write("run_state", state)
        again = self.scheduled("run", error=ApiError("The meal service returned HTTP 500.", 500, "meal service"))
        self.assertEqual(again, [])

    def test_suspension_alerts_once_when_it_happens(self):
        self.assertIn("Booking problem", self.scheduled("run", error=self.rejected())[0])
        state = self.store.read("run_state")
        state["retry_after"] = "2000-01-01T00:00:00+00:00"
        self.store.write("run_state", state)
        sent = self.scheduled("run", error=self.rejected())
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0].startswith("Booking suspended."))
        self.assertIn(SUSPENDED_NOTICE, sent[0])

    def test_recovery_is_announced(self):
        self.store.write("run_state", {"revision": "one", "failures": 2})

        def recover(args, store, emit):
            self.store.write("run_state", {"revision": "one", "completed": "2026-11-11"})
        self.assertEqual(self.scheduled("run", execute_effect=recover), ["Booking is working again."])


class NotifierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name))

    def test_unconfigured_store_sends_nothing(self):
        with patch("reserve_cli.telegram.TelegramBot") as bot:
            Notifier(self.store).deliver(["hello"])
        bot.assert_not_called()

    def test_messages_go_only_to_the_saved_chat(self):
        self.store.write("telegram", {"token": TOKEN, "chat_id": 42, "name": "Mohaned"})
        with patch("reserve_cli.telegram.TelegramBot") as bot:
            Notifier(self.store).deliver(["one", "two"])
        self.assertEqual([call.args for call in bot.return_value.send.call_args_list], [(42, "one"), (42, "two")])

    def test_delivery_failure_is_logged_and_never_raised(self):
        self.store.write("telegram", {"token": TOKEN, "chat_id": 42, "name": "Mohaned"})
        logged = []
        with patch("reserve_cli.telegram.TelegramBot") as bot:
            bot.return_value.send.side_effect = TelegramError("Could not reach Telegram.")
            Notifier(self.store).deliver(["one"], logged.append)
        self.assertIn("not delivered", logged[0])


class SetupCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name))
        self.output = io.StringIO()
        self.console = Console(file=self.output, width=100)
        self.bot = Mock()
        self.bot.me.return_value = {"username": "ExampleBot"}
        patcher = patch("reserve_cli.short.TelegramBot", return_value=self.bot)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_setup_from_file_saves_the_chat_and_confirms_by_message(self):
        path = Path(self.temporary.name) / "bot.env"
        path.write_text(f"link=https://t.me/Other\nhttp={TOKEN}\n", encoding="utf-8")
        self.console.input = lambda _: ""
        with patch("reserve_cli.short.find_private_chat", return_value={"chat_id": 42, "name": "Mohaned"}):
            self.assertEqual(run(["telegram", str(path)], self.console, self.store), 0)
        self.assertEqual(self.store.read("telegram"), {"token": TOKEN, "chat_id": 42, "name": "Mohaned"})
        self.bot.send.assert_called_once()
        self.assertIn("https://t.me/ExampleBot", self.output.getvalue())
        self.assertNotIn(TOKEN, self.output.getvalue())

    def test_declining_the_name_saves_nothing(self):
        self.console.input = lambda _: "n"
        with patch("reserve_cli.short.find_private_chat", return_value={"chat_id": 42, "name": "Someone"}), \
                patch("reserve_cli.short.getpass.getpass", return_value=TOKEN):
            self.assertEqual(run(["telegram"], self.console, self.store), 0)
        self.assertIsNone(self.store.read("telegram"))

    def test_test_and_off(self):
        self.store.write("telegram", {"token": TOKEN, "chat_id": 42, "name": "Mohaned"})
        self.assertEqual(run(["telegram", "test"], self.console, self.store), 0)
        self.bot.send.assert_called_once()
        self.assertEqual(run(["telegram", "off"], self.console, self.store), 0)
        self.assertIsNone(self.store.read("telegram"))

    def test_doctor_reports_alert_state(self):
        doctor(self.console, self.store)
        self.assertIn("Off", self.output.getvalue())
        self.store.write("telegram", {"token": TOKEN, "chat_id": 42, "name": "Mohaned"})
        doctor(self.console, self.store)
        self.assertIn("sending to Mohaned", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
