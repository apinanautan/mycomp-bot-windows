import unittest
from unittest.mock import patch, MagicMock
from capability_sources import browser_cdp as cdp


class BrowserCdpWindowsTests(unittest.TestCase):
    def test_explicit_port_is_not_overridden_by_saved_port(self):
        with patch.object(cdp, "_CDP_PORT_STATE", MagicMock(read_text=lambda **kwargs: "9224")):
            self.assertEqual(cdp._port({"port": 9225}), 9225)

    def test_saved_port_is_used_for_followup_commands(self):
        with patch.object(cdp, "_CDP_PORT_STATE", MagicMock(read_text=lambda **kwargs: "9224")):
            self.assertEqual(cdp._port({}), 9224)

    def test_port_validation(self):
        with self.assertRaises(ValueError):
            cdp._port({"port": 80})

    def test_profile_is_isolated_by_port(self):
        import inspect
        source = inspect.getsource(cdp.execute)
        self.assertIn('str(_DEFAULT_PROFILE) + f"-work-{port}"', source)

    def test_half_screen_coordinates(self):
        display = {"bounds": {"x": 0, "y": 0, "width": 1536, "height": 864}}
        self.assertEqual(cdp._window_arguments(display), [
            "--window-position=768,0", "--window-size=768,864",
        ])

    def test_existing_tab_is_reused_for_sequential_work(self):
        with patch.object(cdp, "_port", return_value=9273), \
                patch.object(cdp, "_tab", return_value={"id": "task-tab", "url": "about:blank"}), \
                patch.object(cdp, "_with_tab", return_value={"frameId": "ok"}) as navigate, \
                patch.object(cdp, "_json_request") as new_tab:
            result = cdp.execute({"action": "new_tab", "url": "about:blank"})
            self.assertTrue(result["reused"])
            self.assertEqual(result["id"], "task-tab")
            navigate.assert_not_called()
            new_tab.assert_not_called()

    def test_browser_is_visible_not_headless(self):
        import inspect
        source = inspect.getsource(cdp.execute)
        self.assertIn('"--new-window"', source)
        self.assertNotIn('"--headless=new"', source)

    def test_launch_rejects_chrome_command_line_flags(self):
        with patch.object(cdp, "_port_is_busy", return_value=False):
            with self.assertRaises(ValueError):
                cdp.execute({"action": "launch", "port": 9300, "url": "--disable-web-security"})
