"""Regression checks for Windows icon and plugin-creation UI entry points."""
import unittest
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
GUI = (ROOT / "windows" / "MyCompBot.py").read_text(encoding="utf-8")
UPDATE = (ROOT / "windows" / "app_update.py").read_text(encoding="utf-8")


class GuiEntryPointTests(unittest.TestCase):
    def test_dpi_awareness_precedes_tk_and_uses_native_icon_handles(self):
        self.assertLess(GUI.index("SetProcessDpiAwareness(1)"), GUI.index("import tkinter as tk"))
        self.assertIn("SendMessageW(hwnd, 0x0080, slot, handle)", GUI)
        self.assertIn("self.after_idle(self._apply_native_window_icon)", GUI)
        self.assertIn("self.bind(\"<Map>\", self._on_native_window_map", GUI)
        self.assertIn("GetDpiForWindow", GUI)
        self.assertIn("title_size = max(16, round(16 * dpi / 96))", GUI)

    def test_create_plugin_visible_without_opening_settings_dialog(self):
        self.assertEqual(GUI.count('text="สร้างพรอมต์ตั้งค่า MyComp Bot"'), 1)
        self.assertNotIn('text="พรอมต์สร้างปลั๊กอิน"', GUI)
        self.assertEqual(GUI.count("launch_chatgpt=False"), 1)
        self.assertIn("launch_chatgpt=False", GUI)
        self.assertIn("viewer.clipboard_append(prompt)", GUI)
        self.assertIn("https://chatgpt.com/", GUI)
        # No browser URL is made from prompt or Tunnel ID.
        self.assertNotIn('webbrowser.open("https://chatgpt.com/?q=', GUI)

    def test_original_icon_has_all_windows_sizes_and_transparent_corners(self):
        png = Image.open(ROOT / "windows/assets/mycomp-bot.png")
        self.assertEqual(png.size, (1024, 1024))
        with Image.open(ROOT / "windows/assets/mycomp-bot.ico") as icon:
            self.assertGreaterEqual(len(icon.ico.sizes()), 7)
            self.assertIn((20, 20), icon.ico.sizes())
            for size in ((16,16),(20,20),(32,32),(48,48),(256,256)):
                frame = icon.ico.getimage(size).convert("RGBA")
                self.assertEqual(frame.getpixel((0,0))[3],0)

    def test_managed_icon_migration_keeps_user_custom_shortcuts(self):
        self.assertIn("is_managed", GUI)
        self.assertIn("not current or is_managed", GUI)
        self.assertIn("$managedIcon=", UPDATE)
        self.assertIn("-or $managedIcon)", UPDATE)


if __name__ == "__main__":
    unittest.main()