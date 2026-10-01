import io
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


if __name__ == "__main__":
    unittest.main()
