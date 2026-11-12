import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from rich.console import Console

from reserve_cli import update
from reserve_cli.short import run
from reserve_cli.store import Store
from reserve_cli.version import __version__


def response(payload=None, text=""):
    result = Mock()
    result.raise_for_status = Mock()
    result.json = Mock(return_value=payload)
    result.text = text
    return result


class VersionTests(unittest.TestCase):
    def test_versions_compare_numerically(self):
        self.assertTrue(update.is_newer("0.10.0", "0.9.1"))
        self.assertFalse(update.is_newer("0.9.1", "0.9.1"))
        self.assertFalse(update.is_newer("0.8.9", "0.9.1"))
        with self.assertRaises(update.UpdateError):
            update.parse_version("latest")

    def test_pyproject_and_module_versions_agree(self):
        import tomllib
        project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["version"], __version__)


class ReleaseLookupTests(unittest.TestCase):
    def test_latest_release_reads_the_tag(self):
        with patch("reserve_cli.update.requests.get", return_value=response({"tag_name": "v1.2.3"})):
            release = update.latest_release()
        self.assertEqual((release.version, release.tag), ("1.2.3", "v1.2.3"))

    def test_odd_tags_are_refused(self):
        with patch("reserve_cli.update.requests.get", return_value=response({"tag_name": "nightly"})):
            with self.assertRaises(update.UpdateError):
                update.latest_release()

    def test_checksum_must_name_the_archive(self):
        release = update.Release("1.2.3", "v1.2.3")
        name = update.archive_name("1.2.3")
        with patch("reserve_cli.update.requests.get", return_value=response(text=f"{'a' * 64}  {name}\n")):
            self.assertEqual(update.published_digest(release), "a" * 64)
        with patch("reserve_cli.update.requests.get", return_value=response(text=f"{'a' * 64}  other.zip\n")):
            with self.assertRaises(update.UpdateError):
                update.published_digest(release)


class LinuxInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.app_dir = Path(self.temp.name) / "app"
        self.app_dir.mkdir()
        (self.app_dir / "ate").write_bytes(b"old")
        self.release = update.Release("1.2.3", "v1.2.3")
        self.archive = Path(self.temp.name) / "release.tar.gz"
        payload = Path(self.temp.name) / "ate"
        payload.write_bytes(b"new program")
        with tarfile.open(self.archive, "w:gz") as bundle:
            bundle.add(payload, arcname="Ate-1.2.3-linux/ate")
        self.digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def install(self, digest, started):
        def fake_download(url, target):
            target.write_bytes(self.archive.read_bytes())
        with patch("reserve_cli.update.download", fake_download), \
                patch("reserve_cli.update.published_digest", return_value=digest), \
                patch("reserve_cli.update.on_linux", return_value=True), \
                patch("reserve_cli.update.on_windows", return_value=False), \
                patch("reserve_cli.update.subprocess.run", return_value=started):
            update.install_linux(self.release, self.app_dir)

    def test_verified_download_replaces_the_executable(self):
        self.install(self.digest, Mock(returncode=0, stdout="Ate 1.2.3\n"))
        self.assertEqual((self.app_dir / "ate").read_bytes(), b"new program")
        self.assertEqual([path.name for path in self.app_dir.iterdir()], ["ate"])

    def test_checksum_mismatch_changes_nothing(self):
        with self.assertRaisesRegex(update.UpdateError, "checksum"):
            self.install("0" * 64, Mock(returncode=0, stdout="Ate 1.2.3\n"))
        self.assertEqual((self.app_dir / "ate").read_bytes(), b"old")

    def test_a_program_reporting_the_wrong_version_is_not_installed(self):
        with self.assertRaisesRegex(update.UpdateError, "version"):
            self.install(self.digest, Mock(returncode=0, stdout="Ate 0.0.1\n"))
        self.assertEqual((self.app_dir / "ate").read_bytes(), b"old")


class BackgroundCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))

    def test_newer_release_is_applied_once_per_day(self):
        newer = update.Release("99.0.0", "v99.0.0")
        with patch("reserve_cli.update.blocker", return_value=None), \
                patch("reserve_cli.update.on_linux", return_value=True), \
                patch("reserve_cli.update.on_windows", return_value=False), \
                patch("reserve_cli.update.latest_release", return_value=newer) as lookup, \
                patch("reserve_cli.update.apply") as apply:
            logs, alerts = update.background(self.store)
            update.background(self.store)
        self.assertEqual(lookup.call_count, 1)
        apply.assert_called_once_with(newer)
        self.assertIn("99.0.0", logs[0])
        self.assertEqual(alerts, [])

    def test_windows_hands_the_swap_to_the_elevated_task(self):
        newer = update.Release("99.0.0", "v99.0.0")
        with patch("reserve_cli.update.blocker", return_value=None), \
                patch("reserve_cli.update.on_windows", return_value=True), \
                patch("reserve_cli.update.on_linux", return_value=False), \
                patch("reserve_cli.update.latest_release", return_value=newer), \
                patch("reserve_cli.update.start_windows_update") as start, \
                patch("reserve_cli.update.apply") as apply:
            update.background(self.store)
        start.assert_called_once()
        apply.assert_not_called()

    def test_switching_auto_update_off_skips_the_check(self):
        update.set_autoupdate(self.store, False)
        with patch("reserve_cli.update.blocker", return_value=None), \
                patch("reserve_cli.update.latest_release") as lookup:
            update.background(self.store)
        lookup.assert_not_called()

    def test_a_failed_lookup_is_logged_and_not_raised(self):
        with patch("reserve_cli.update.blocker", return_value=None), \
                patch("reserve_cli.update.latest_release", side_effect=update.UpdateError("offline")):
            logs, alerts = update.background(self.store)
        self.assertEqual(logs, ["Automatic update did not finish: offline"])

    def test_a_changed_version_sends_one_alert(self):
        self.store.write("update", {"running_version": "0.0.1", "checked_at": update._now().isoformat()})
        logs, alerts = update.background(self.store)
        self.assertEqual(len(alerts), 1)
        self.assertIn("0.0.1", alerts[0])
        self.assertIn(__version__, alerts[0])
        self.assertEqual(update.background(self.store)[1], [])

    def test_a_copy_that_cannot_update_itself_never_checks(self):
        with patch("reserve_cli.update.blocker", return_value="not installed"), \
                patch("reserve_cli.update.latest_release") as lookup:
            update.background(self.store)
        lookup.assert_not_called()


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))
        self.output = io.StringIO()
        self.console = Console(file=self.output, force_terminal=False, width=100)

    def test_version_prints_the_running_version(self):
        self.assertEqual(run(["version"], self.console, self.store), 0)
        self.assertIn(f"Ate {__version__}", self.output.getvalue())

    def test_update_check_reports_a_newer_release_without_installing(self):
        with patch("reserve_cli.update.latest_release", return_value=update.Release("99.0.0", "v99.0.0")), \
                patch("reserve_cli.update.apply") as apply:
            self.assertEqual(run(["update", "check"], self.console, self.store), 0)
        apply.assert_not_called()
        self.assertIn("99.0.0 is available", self.output.getvalue())

    def test_update_reports_when_already_current(self):
        with patch("reserve_cli.update.latest_release", return_value=update.Release(__version__, f"v{__version__}")):
            self.assertEqual(run(["update"], self.console, self.store), 0)
        self.assertIn("latest version", self.output.getvalue())

    def test_config_autoupdate_toggles_the_setting(self):
        run(["config", "autoupdate", "off"], self.console, self.store)
        self.assertFalse(update.autoupdate_enabled(self.store))
        run(["config", "autoupdate", "on"], self.console, self.store)
        self.assertTrue(update.autoupdate_enabled(self.store))


if __name__ == "__main__":
    unittest.main()
