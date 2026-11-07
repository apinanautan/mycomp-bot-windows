"""Manual MyComp setup clipboard controls, persistent names, no secrets."""
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from windows.plugin_setup_copy import base_name, copy_value
from windows import MyCompBot as gui


TEST_TUNNEL_ID = "tunnel_" + "abcdef0123456789" * 2
SETTINGS = {
    "tunnel_id": TEST_TUNNEL_ID,
    "enabled": True,
    "api_key": "sk-never-expose-this-value",
}


class PluginCopyTests(unittest.TestCase):
    def test_copy_names_are_derived_from_saved_base_not_machine_hostname(self):
        self.assertEqual(copy_value("tailscale_name", "BotWen", SETTINGS),
                         "BotWen Tailscale")
        self.assertEqual(copy_value("tunnel_name", "BotWen", SETTINGS),
                         "BotWen Tunnel")
        self.assertEqual(copy_value("tailscale_name", "MyComp BotS", SETTINGS),
                         "MyComp BotS Tailscale")

    def test_copy_saved_tunnel_identifier_without_key(self):
        self.assertEqual(copy_value("tunnel_id", "BotWen", SETTINGS),
                         TEST_TUNNEL_ID)
        with self.assertRaisesRegex(ValueError, "Tunnel ID"):
            copy_value("tunnel_id", "BotWen", {"api_key": "sk-shared-secret"})
        with self.assertRaisesRegex(ValueError, "Tunnel ID"):
            copy_value("tunnel_id", "BotWen", {"tunnel_id": "tunnel_bad"})

    def test_main_channel_name_is_not_fabricated_channel_id(self):
        self.assertEqual(copy_value("channel_name", "BotWen", SETTINGS), "main")
        with self.assertRaisesRegex(ValueError, "Channel ID"):
            copy_value("channel_id", "BotWen", SETTINGS)
        self.assertEqual(
            copy_value("channel_id", "BotWen", {"channel_id": "channel_123"}),
            "channel_123",
        )

    def test_rejects_empty_or_control_character_name(self):
        for name in ("", " " * 8, "Oops\nBad", "a" * 71):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    base_name(name)

    def test_gui_copy_persists_name_and_places_correct_field_on_clipboard(self):
        bot = object.__new__(gui.MyCompBot)
        bot.plugin_base_name = Mock()
        bot.plugin_base_name.get.return_value = " BotWen "
        bot.plugin_copy_status = Mock()
        bot.openai_tunnel = Mock()
        bot.openai_tunnel.load.return_value = SETTINGS
        bot.clipboard_clear = Mock()
        bot.clipboard_append = Mock()
        bot.update_idletasks = Mock()
        saved = []
        with patch.object(gui, "_read_env", return_value={"MYCOMP_PUBLIC_BASE_URL": "https://example.ts.net"}), \
             patch.object(gui, "_write_env", side_effect=lambda value: saved.append(value)):
            value = gui.MyCompBot._copy_plugin_setup_field(bot, "tunnel_id")
        self.assertEqual(value, TEST_TUNNEL_ID)
        self.assertEqual(saved[0]["MYCOMP_PLUGIN_BASE_NAME"], "BotWen")
        self.assertEqual(saved[0]["MYCOMP_PUBLIC_BASE_URL"], "https://example.ts.net")
        bot.clipboard_append.assert_called_once_with(TEST_TUNNEL_ID)
        self.assertNotIn("api_key", saved[0])

    def test_missing_channel_id_does_not_clear_clipboard(self):
        bot = object.__new__(gui.MyCompBot)
        bot.plugin_base_name = Mock()
        bot.plugin_base_name.get.return_value = "BotWen"
        bot.plugin_copy_status = Mock()
        bot.openai_tunnel = Mock()
        bot.openai_tunnel.load.return_value = SETTINGS
        bot.clipboard_clear = Mock()
        bot.clipboard_append = Mock()
        with patch.object(gui, "_read_env", return_value={"MYCOMP_PLUGIN_BASE_NAME": "BotWen"}):
            result = gui.MyCompBot._copy_plugin_setup_field(bot, "channel_id")
        self.assertIsNone(result)
        bot.clipboard_clear.assert_not_called()
        bot.clipboard_append.assert_not_called()

    def test_prompt_remains_available_and_uses_last_saved_name(self):
        source = (Path(__file__).resolve().parents[1] / "windows/MyCompBot.py").read_text(encoding="utf-8")
        self.assertIn('text="สร้างพรอมต์ตั้งค่า MyComp Bot"', source)
        self.assertIn('initialvalue=self.plugin_base_name.get().strip() or "MyComp Bot"', source)
        for kind in ("tailscale_name", "tunnel_name", "tunnel_id", "channel_name", "channel_id"):
            self.assertIn(f'"{kind}"', source)
