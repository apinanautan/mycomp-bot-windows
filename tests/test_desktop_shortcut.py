import os
import shutil
import tempfile
import unittest
from pathlib import Path

from windows.desktop_shortcut import ensure_desktop_shortcut, windows_desktop_directory

ROOT = Path(__file__).resolve().parents[1]


class DesktopShortcutTests(unittest.TestCase):
    def test_installer_creates_shortcut_after_health_check(self):
        script = (ROOT / "windows/Install MyComp Bot.ps1").read_text(encoding="utf-8")
        self.assertIn("from windows.desktop_shortcut import ensure_desktop_shortcut", script)
        self.assertLess(script.index("if (-not $healthy)"), script.index("$shortcutCode ="))
        self.assertLess(script.index("if ($PlanOnly)"), script.index("$shortcutCode ="))
        gui = (ROOT / "windows/MyCompBot.py").read_text(encoding="utf-8")
        self.assertIn("desktop_shortcut.ensure_desktop_shortcut(ROOT)", gui)
        updater = (ROOT / "windows/app_update.py").read_text(encoding="utf-8")
        self.assertIn("GetFolderPath('DesktopDirectory')", updater)

    def test_save_and_connect_really_enables_tunnel_and_explains_plugin_setup(self):
        gui = (ROOT / "windows/MyCompBot.py").read_text(encoding="utf-8")
        self.assertIn("enabled.set(True)", gui)
        self.assertIn("self.openai_tunnel.save(tunnel_id.get(), key.get(), True)", gui)
        self.assertIn("self.openai_tunnel.activate_profile(name)", gui)
        self.assertIn("ChatGPT plugin must still be installed and authorized separately", gui)

    @unittest.skipUnless(os.name == "nt", "Windows COM shortcut test")
    def test_windows_creates_actual_desktop_lnk_once_without_overwriting_other_app(self):
        from win32com.client import Dispatch

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            desktop = base / "Desktop"
            desktop.mkdir()

            def fake_app(name):
                root = base / name
                (root / ".venv/Scripts").mkdir(parents=True)
                (root / "windows/assets").mkdir(parents=True)
                (root / ".venv/Scripts/pythonw.exe").write_bytes(b"fake-executable")
                (root / "windows/MyCompBot.py").write_text("# fake")
                shutil.copyfile(
                    ROOT / "windows/assets/mycomp-bot.ico",
                    root / "windows/assets/mycomp-bot.ico",
                )
                return root

            first = fake_app("MyComp Bot")
            self.assertEqual(ensure_desktop_shortcut(first, desktop=desktop), "created")
            link_path = desktop / "MyComp Bot.lnk"
            self.assertTrue(link_path.is_file())
            link = Dispatch("WScript.Shell").CreateShortcut(str(link_path))
            self.assertEqual(Path(link.TargetPath).resolve(), (first / ".venv/Scripts/pythonw.exe").resolve())
            self.assertIn("MyCompBot.py", link.Arguments)
            self.assertIn("mycomp-bot.ico", link.IconLocation)
            self.assertEqual(ensure_desktop_shortcut(first, desktop=desktop), "present")

            other = fake_app("Other Product")
            self.assertEqual(ensure_desktop_shortcut(other, desktop=desktop), "conflict")
            same_link = Dispatch("WScript.Shell").CreateShortcut(str(link_path))
            self.assertEqual(Path(same_link.TargetPath).resolve(), (first / ".venv/Scripts/pythonw.exe").resolve())

    @unittest.skipUnless(os.name == "nt", "Windows shell known folder test")
    def test_desktop_location_uses_shell_known_folder(self):
        self.assertTrue(windows_desktop_directory().is_dir())
