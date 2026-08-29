import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch


@unittest.skipUnless(os.name == "nt", "Windows host only")
class WindowsHostTests(unittest.TestCase):
    def test_autostart_registry_value_uses_current_pythonw_and_host(self):
        from windows import MyCompBot as app

        command = subprocess.list2cmdline([
            str(app.ROOT / ".venv" / "Scripts" / "pythonw.exe"),
            str(app.Path(app.__file__).resolve()),
        ])
        fake = MagicMock(HKEY_CURRENT_USER=object(), REG_SZ=1)
        key = fake.CreateKey.return_value.__enter__.return_value
        with patch.object(app, "winreg", fake):
            app._set_autostart(True)
            fake.SetValueEx.assert_called_once_with(key, app.AUTOSTART_NAME, 0, 1, command)
            app._set_autostart(False)
            fake.DeleteValue.assert_called_once_with(key, app.AUTOSTART_NAME)


if __name__ == "__main__":
    unittest.main()
