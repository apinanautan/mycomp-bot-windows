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
        self.assertIn('str(_DEFAULT_PROFILE) + f"-{port}"', source)
