import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from rich.console import Console

from reserve_cli import where
from reserve_cli.short import doctor, main, run
from reserve_cli.store import Store


class LocalSwitchTests(unittest.TestCase):
    def test_windows_task_states_map_to_on_off_and_missing(self):
        with patch("reserve_cli.where.sys.platform", "win32"):
            for code, expected in ((11, True), (10, False), (2, None), (3, None)):
                with patch("reserve_cli.where.powershell", return_value=Mock(returncode=code)):
                    self.assertIs(where.local_state(), expected)
            with patch("reserve_cli.where.powershell", return_value=Mock(returncode=1)):
                with self.assertRaises(where.WhereError):
                    where.local_state()

    def test_switching_needs_an_installed_scheduler(self):
        with patch("reserve_cli.where.local_state", return_value=None):
            with self.assertRaisesRegex(where.WhereError, "nothing to switch"):
                where.set_local(False)

    def test_windows_disable_runs_the_fixed_script_for_the_ate_task_only(self):
        with patch("reserve_cli.where.sys.platform", "win32"), \
                patch("reserve_cli.where.local_state", return_value=True), \
                patch("reserve_cli.where.powershell", return_value=Mock(returncode=0)) as shell:
            where.set_local(False)
        script = shell.call_args.args[0]
        self.assertIn("Disable-ScheduledTask -TaskName 'Ate'", script)
        self.assertIn("-notlike 'Ate:*'", script)


class CloudSwitchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name))

    def test_server_address_is_validated_before_it_is_saved(self):
        for bad in ("-oProxyCommand=evil@host", "root@host; reboot", "no-at-sign", "root@"):
            with self.subTest(bad=bad), self.assertRaises(where.WhereError):
                where.save_cloud(self.store, bad, 22)
        with self.assertRaises(where.WhereError):
            where.save_cloud(self.store, "root@host", 70000)
        self.assertIsNone(where.cloud_target(self.store))

    def test_saved_server_keeps_other_settings(self):
        self.store.write("config", {"interval_minutes": 15})
        where.save_cloud(self.store, "root@box.example.com", 9194)
        self.assertEqual(self.store.read("config"),
                         {"interval_minutes": 15, "cloud": {"target": "root@box.example.com", "port": 9194}})

    def test_remote_commands_are_fixed_and_separated_from_options(self):
        where.save_cloud(self.store, "root@box.example.com", 9194)
        with patch("reserve_cli.where.shutil.which", return_value="ssh"), \
                patch("reserve_cli.where.subprocess.run", return_value=Mock(returncode=0, stdout="x", stderr="")) as ssh:
            where.remote(self.store, "off")
        command = ssh.call_args.args[0]
        self.assertEqual(command[-3:], ["--", "root@box.example.com", "ate pause"])
        self.assertEqual(command[1:3], ["-p", "9194"])

    def test_cloud_state_reads_the_standing_order(self):
        where.save_cloud(self.store, "root@box.example.com", 22)
        for text, expected in (("Standing order  Next 90 day(s)  ACTIVE", True), ("... PAUSED", False), ("???", None)):
            with patch("reserve_cli.where.remote", return_value=text):
                self.assertIs(where.cloud_state(self.store), expected)

    def test_unconfigured_cloud_says_how_to_set_it_up(self):
        with self.assertRaisesRegex(where.WhereError, "cloud setup"):
            where.remote(self.store, "on")

    def test_ssh_failure_mentions_the_key_passphrase(self):
        where.save_cloud(self.store, "root@box.example.com", 22)
        with patch("reserve_cli.where.shutil.which", return_value="ssh"), \
                patch("reserve_cli.where.subprocess.run",
                      return_value=Mock(returncode=255, stdout="", stderr="Permission denied (publickey).")):
            with self.assertRaisesRegex(where.WhereError, "ssh-add"):
                where.remote(self.store, "state")


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(Path(self.temporary.name))
        self.output = io.StringIO()
        self.console = Console(file=self.output, width=100)

    def test_local_off_and_on_report_the_new_state(self):
        with patch("reserve_cli.where.set_local") as switch:
            with patch("reserve_cli.where.local_state", return_value=False):
                self.assertEqual(run(["local", "off"], self.console, self.store), 0)
            switch.assert_called_with(False)
            with patch("reserve_cli.where.local_state", return_value=True):
                self.assertEqual(run(["local", "on"], self.console, self.store), 0)
            switch.assert_called_with(True)
        self.assertIn("Local booking (this machine): OFF", self.output.getvalue())
        self.assertIn("Local booking (this machine): ON", self.output.getvalue())

    def test_cloud_setup_then_switch(self):
        self.assertEqual(run(["cloud", "setup", "root@box.example.com", "9194"], self.console, self.store), 0)
        with patch("reserve_cli.where.set_cloud", return_value=False) as switch:
            self.assertEqual(run(["cloud", "off"], self.console, self.store), 0)
        switch.assert_called_once_with(self.store, False)
        self.assertIn("Cloud booking (server): OFF", self.output.getvalue())

    def test_bad_arguments_get_usage_not_a_crash(self):
        for argv in (["local", "maybe"], ["cloud", "on", "now"], ["cloud", "setup"], ["cloud", "setup", "a@b", "x"]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                run(argv, self.console, self.store)

    def test_doctor_lists_local_and_cloud(self):
        with patch("reserve_cli.where.local_state", return_value=False):
            doctor(self.console, self.store)
        self.assertIn("Local booking", self.output.getvalue())
        self.assertIn("Cloud server", self.output.getvalue())


if __name__ == "__main__":
    unittest.main()
