import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from windows import app_update as update


class AppUpdateTests(unittest.TestCase):
    def test_version_comparison_is_numeric_and_rejects_nonrelease_input(self):
        self.assertGreater(update.version_tuple("v1.10.0"), update.version_tuple("1.9.9"))
        for value in ("main", "v1.2.3/../../x", "1.2.3-beta"):
            with self.assertRaises(ValueError):
                update.version_tuple(value)

    def make_archive(self, root, extra=None, version="1.1.4"):
        archive = root / "release.zip"
        files = {"windows/MyCompBot.py": "app", "windows/app_update.py": "helper",
                 "requirements.lock": "", "pyproject.toml": "project", "VERSION": version}
        with zipfile.ZipFile(archive, "w") as bundle:
            for name, content in files.items():
                bundle.writestr("mycomp-bot-windows-1.1.4/" + name, content)
            if extra:
                bundle.writestr(extra, "unsafe")
        return archive

    def test_archive_requires_matching_version_and_complete_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = self.make_archive(root)
            source = update.extract_release(archive, root / "stage", "v1.1.4")
            self.assertEqual((source / "VERSION").read_text(), "1.1.4")
            with self.assertRaises(ValueError):
                update.extract_release(archive, root / "other", "v1.1.5")

    def test_archive_rejects_traversal_and_local_configuration(self):
        for name in ("mycomp-bot-windows-1.1.4/../../escape", "mycomp-bot-windows-1.1.4/.env",
                     "mycomp-bot-windows-1.1.4/.venv/Scripts/python.exe"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.assertRaises(ValueError):
                    update.extract_release(self.make_archive(root, name), root / "stage", "v1.1.4")
                self.assertFalse((root / "escape").exists())

    def test_apply_preserves_local_files_and_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, stage = base / "app", base / "stage"
            root.mkdir(); stage.mkdir()
            (root / "app.py").write_text("old")
            (root / ".env").write_text("private")
            (root / ".venv").mkdir()
            (root / ".venv/local").write_text("environment")
            (root / "notes.txt").write_text("user file")
            (stage / "app.py").write_text("new")
            update.apply_files(root, stage, io.StringIO(), install=lambda root, log: None)
            self.assertEqual((root / "app.py").read_text(), "new")
            self.assertEqual((root / ".env").read_text(), "private")
            self.assertEqual((root / "notes.txt").read_text(), "user file")
            self.assertEqual((root / ".venv/local").read_text(), "environment")

    def test_failed_install_restores_old_files_and_removes_new_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, stage = base / "app", base / "stage"
            root.mkdir(); stage.mkdir()
            (root / "app.py").write_text("old")
            (stage / "app.py").write_text("new")
            (stage / "added.py").write_text("new file")
            with self.assertRaises(RuntimeError):
                update.apply_files(root, stage, io.StringIO(), install=lambda root, log: (_ for _ in ()).throw(RuntimeError("pip failed")))
            self.assertEqual((root / "app.py").read_text(), "old")
            self.assertFalse((root / "added.py").exists())

    def test_dirty_checkout_is_rejected_before_replacing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            with patch.object(update.shutil, "which", return_value="git"), patch.object(update.subprocess, "run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = " M windows/MyCompBot.py"
                with self.assertRaises(RuntimeError):
                    update.check_checkout(root)

    def test_parent_exit_timeout_never_replaces_files_or_launches_second_app(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            arguments = ['update', '--root', str(base), '--source', str(base),
                         '--parent-pid', '1234', '--log', str(base / 'update.log')]
            with patch.object(sys, 'argv', arguments), \
                 patch.object(update, 'wait_for_parent', side_effect=RuntimeError('parent still running')), \
                 patch.object(update, 'apply_files') as apply, \
                 patch.object(update, 'restart') as restart, \
                 patch.object(update.ctypes, 'windll', create=True):
                update.main()
            apply.assert_not_called()
            restart.assert_not_called()



    def test_managed_upgrade_uses_separate_directory_for_dirty_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            checkout = base / "working-checkout"
            source = base / "updates" / "source"
            data = base / "user-data"
            checkout.mkdir()
            (checkout / ".git").mkdir()
            (checkout / "notes.txt").write_text("do not overwrite")
            source.mkdir(parents=True)
            (source / "VERSION").write_text("1.1.10")
            (source / "windows").mkdir()
            (source / "windows/MyCompBot.py").write_text("new version")
            created = []

            def make_venv(command, **kwargs):
                root = Path(command[-1]).parent
                (root / ".venv/Scripts").mkdir(parents=True)
                (root / ".venv/Scripts/pythonw.exe").touch()
                created.append(command)
                return None

            def simulate_install(root, log):
                (root / "dependencies-ready.txt").write_text("yes")

            with patch.object(update.subprocess, "run", side_effect=make_venv):
                installed = update.install_managed_release(
                    source, data, Path(sys.executable), io.StringIO(),
                    install=simulate_install,
                )
            self.assertEqual(installed, data / "versions/v1.1.10")
            self.assertNotEqual(installed, checkout)
            self.assertEqual((checkout / "notes.txt").read_text(), "do not overwrite")
            self.assertTrue((checkout / ".git").is_dir())
            self.assertTrue((installed / ".mycomp-install-complete").exists())
            self.assertTrue((installed / "dependencies-ready.txt").is_file())
            self.assertEqual(len(created), 1)
            with patch.object(update.subprocess, "run") as run_again:
                self.assertEqual(
                    update.install_managed_release(
                        source, data, Path(sys.executable), io.StringIO(),
                        install=simulate_install,
                    ), installed,
                )
            run_again.assert_not_called()

    def test_managed_install_failure_does_not_touch_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "updates/source"
            data = base / "data"
            source.mkdir(parents=True)
            (source / "VERSION").write_text("1.1.10")
            checkout = base / "checkout"
            checkout.mkdir()
            (checkout / ".git").mkdir()
            (checkout / "important.py").write_text("unchanged")
            def fake_venv(command, **kwargs):
                (Path(command[-1]) / "Scripts").mkdir(parents=True)
            def fail_install(root, log):
                raise RuntimeError("simulated dependency install failure")
            with patch.object(update.subprocess, "run", side_effect=fake_venv):
                with self.assertRaisesRegex(RuntimeError, "simulated dependency"):
                    update.install_managed_release(
                        source, data, Path(sys.executable), io.StringIO(),
                        install=fail_install,
                    )
            self.assertFalse((data / "versions/v1.1.10").exists())
            self.assertEqual((checkout / "important.py").read_text(), "unchanged")

    def test_incomplete_managed_copy_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "updates/source"
            source.mkdir(parents=True)
            (source / "VERSION").write_text("1.1.10")
            target = base / "data/versions/v1.1.10"
            target.mkdir(parents=True)
            (target / "important.txt").write_text("preserved")
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                update.install_managed_release(
                    source, base / "data", Path(sys.executable), io.StringIO(),
                )
            self.assertEqual((target / "important.txt").read_text(), "preserved")

    def test_launcher_retarget_uses_only_original_app_paths(self):
        import base64
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            previous = base / "old"
            installed = base / "new"
            previous.mkdir()
            installed.mkdir()
            with patch.object(update.subprocess, "run") as invoke, \
                 patch("winreg.OpenKey", side_effect=FileNotFoundError()):
                invoke.return_value.returncode = 0
                update.redirect_launchers(previous, installed, io.StringIO())
            args = invoke.call_args.args[0]
            self.assertEqual(args[0], "powershell.exe")
            command = base64.b64decode(args[-1]).decode("utf-16le")
            self.assertIn(str(previous), command)
            self.assertIn("User Pinned", command)
            self.assertIn("TaskBar", command)
            self.assertIn("MyComp Bot.lnk", command)
            self.assertIn(str(installed), command)
            self.assertIn("MyComp Bot.lnk", command)
            self.assertIn("mycomp-bot.ico", command)
            self.assertIn("OrdinalIgnoreCase", command)
            self.assertIn("$managedExe=", command)
            self.assertIn("$ifManaged=", command)
            self.assertIn("[char]34+$newScript+[char]34", command)
            self.assertNotIn("$link.Arguments='"'+$newScript+'"'", command)


    def test_updater_creates_desktop_shortcut_only_when_missing(self):
        import base64
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            old, new = base / "old", base / "new"
            old.mkdir()
            new.mkdir()
            with patch.object(update.subprocess, "run") as invoke, \
                 patch("winreg.OpenKey", side_effect=FileNotFoundError()):
                invoke.return_value.returncode = 0
                update.redirect_launchers(old, new, io.StringIO())
            ps = base64.b64decode(invoke.call_args.args[0][-1]).decode("utf-16le")
            self.assertIn("if(-not (Test-Path -LiteralPath $desktop))", ps)
            self.assertIn("$shortcut=$shell.CreateShortcut($desktop)", ps)
            self.assertIn("$shortcut.TargetPath=$newExe", ps)
            self.assertIn("$shortcut.IconLocation=$newIcon+',0'", ps)
            self.assertIn("if([string]::IsNullOrWhiteSpace($link.IconLocation))", ps)
            self.assertNotIn("$link.IconLocation=$newIcon+',0';$link.Save()", ps)

    def test_update_worker_allows_dirty_checkout_without_overwriting(self):
        import queue
        from windows import MyCompBot as gui
        bot = object.__new__(gui.MyCompBot)
        bot.update_queue = queue.Queue()
        with patch.object(gui.app_update, "latest_release", return_value={
            "tag": "v1.1.10", "url": "https://example.test/archive.zip",
        }), patch.object(gui.app_update, "check_checkout", side_effect=AssertionError("should not check dirty checkout")):
            with patch.object(gui, "APP_VERSION", "1.1.9"):
                gui.MyCompBot._check_update_worker(bot)
        kind, data = bot.update_queue.get_nowait()
        self.assertEqual(kind, "available")
        self.assertEqual(data["tag"], "v1.1.10")

    def test_same_version_checkout_offers_safe_managed_install(self):
        import queue
        from windows import MyCompBot as gui
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "source"
            checkout.mkdir()
            (checkout / ".git").mkdir()
            bot = object.__new__(gui.MyCompBot)
            bot.update_queue = queue.Queue()
            with patch.object(gui, "ROOT", checkout), patch.object(gui, "APP_VERSION", "1.1.11"), \
                 patch.object(gui.app_update, "latest_release", return_value={
                     "tag": "v1.1.11", "url": "https://example.test/release.zip",
                 }):
                gui.MyCompBot._check_update_worker(bot)
            event, release = bot.update_queue.get_nowait()
            self.assertEqual(event, "migrate")
            self.assertEqual(release["tag"], "v1.1.11")

    def test_same_version_managed_install_remains_current(self):
        import queue
        from windows import MyCompBot as gui
        with tempfile.TemporaryDirectory() as directory:
            bot = object.__new__(gui.MyCompBot)
            bot.update_queue = queue.Queue()
            with patch.object(gui, "ROOT", Path(directory)), \
                 patch.object(gui, "APP_VERSION", "1.1.11"), \
                 patch.object(gui.app_update, "latest_release", return_value={
                     "tag": "v1.1.11", "url": "https://example.test/release.zip",
                 }):
                gui.MyCompBot._check_update_worker(bot)
            event, tag = bot.update_queue.get_nowait()
            self.assertEqual((event, tag), ("current", "v1.1.11"))

    def test_handoff_installs_managed_copy_only_after_parent_exit(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "source-checkout"
            source = root / "updates" / "staged-release"
            checkout.mkdir()
            (checkout / ".git").mkdir()
            (checkout / "user-work.txt").write_text("local edits")
            source.mkdir(parents=True)
            (source / "VERSION").write_text("1.1.10")
            managed = root / "versions/v1.1.10"
            process = unittest.mock.MagicMock()
            process.poll.return_value = None
            response = unittest.mock.MagicMock()
            response.__enter__.return_value = io.BytesIO(json.dumps({
                "status": "ok", "service": "mycomp-bot",
            }).encode())
            argv = ["update", "--root", str(checkout), "--source", str(source),
                    "--parent-pid", "1234", "--log", str(root / "update.log")]
            with patch.object(sys, "argv", argv), \
                 patch.object(update, "wait_for_parent") as waited, \
                 patch.object(update, "install_managed_release", return_value=managed) as installed, \
                 patch.object(update, "restart", return_value=process) as started, \
                 patch.object(update, "redirect_launchers") as redirected, \
                 patch.object(update, "apply_files", side_effect=AssertionError("checkout overlay forbidden")), \
                 patch.object(update.urllib.request, "urlopen", return_value=response):
                update.main()
            waited.assert_called_once_with(1234)
            self.assertEqual(installed.call_args.args[0], source)
            started.assert_called_once_with(managed)
            redirected.assert_called_once()
            self.assertEqual((checkout / "user-work.txt").read_text(), "local edits")


if __name__ == "__main__":
    unittest.main()
