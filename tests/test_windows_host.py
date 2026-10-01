import os
import subprocess
import unittest
from unittest.mock import MagicMock, patch


@unittest.skipUnless(os.name == "nt", "Windows host only")
class WindowsHostTests(unittest.TestCase):
    def setUp(self):
        from windows import MyCompBot as app
        for name, value in {"TAILSCALE_HOST": "example.test.ts.net", "TAILSCALE_HTTPS_PORT": 443,
                            "TAILSCALE_PATH": "/mycomp", "TAILSCALE_PUBLIC_HEALTH": "https://example.test.ts.net/mycomp/health"}.items():
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_funnel_endpoint_uses_this_installation_domain_port_and_path(self):
        from windows import MyCompBot as app
        app._configure_tailscale_endpoint("https://another.tailnet.ts.net:8443/bot")
        self.assertEqual(app.TAILSCALE_HOST, "another.tailnet.ts.net")
        self.assertEqual(app.TAILSCALE_HTTPS_PORT, 8443)
        self.assertEqual(app.TAILSCALE_PATH, "/bot")
        self.assertEqual(app.TAILSCALE_PUBLIC_HEALTH, "https://another.tailnet.ts.net:8443/bot/health")

    def test_stop_terminates_only_owned_engine_process_tree(self):
        from windows import MyCompBot as app
        instance = app.MyCompBot.__new__(app.MyCompBot)
        instance.process = MagicMock(pid=1234)
        instance.process.poll.return_value = None
        instance.status = MagicMock()
        with patch.object(app.subprocess, "run") as run:
            instance._stop()
        self.assertEqual(run.call_args.args[0], ["taskkill.exe", "/PID", "1234", "/T", "/F"])

    def test_update_handoff_uses_base_python_and_quits_only_after_launch(self):
        from windows import MyCompBot as app
        import queue
        instance = app.MyCompBot.__new__(app.MyCompBot)
        instance.update_queue = queue.Queue()
        instance.update_queue.put(("ready", app.Path("C:/staged/source")))
        instance._quit = MagicMock()
        with patch.object(app.shutil, "copy2"), patch.object(app.subprocess, "Popen") as launch:
            instance._process_update_events()
        arguments = launch.call_args.args[0]
        self.assertEqual(arguments[0], str(getattr(app.sys, "_base_executable", app.sys.executable)))
        self.assertIn("--parent-pid", arguments)
        self.assertIn("C:\\staged\\source", arguments)
        instance._quit.assert_called_once()

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

    def test_funnel_route_check_uses_only_mycomp_path(self):
        from windows import MyCompBot as app

        status = {
            "Web": {
                f"{app.TAILSCALE_HOST}:443": {
                    "Handlers": {
                        "/": {"Proxy": "http://127.0.0.1:8765"},
                        "/mycomp": {"Proxy": "http://127.0.0.1:8645"},
                    }
                }
            }
        }
        self.assertTrue(app._funnel_route_is_mycomp(status))
        status["Web"][f"{app.TAILSCALE_HOST}:443"]["Handlers"]["/mycomp"]["Proxy"] = "http://127.0.0.1:9999"
        self.assertFalse(app._funnel_route_is_mycomp(status))

    def test_funnel_repair_turns_off_only_mapped_path(self):
        from windows import MyCompBot as app

        with patch.object(app, "_tailscale_command", return_value="tailscale.exe"), patch.object(
            app.subprocess, "run", side_effect=[MagicMock(returncode=0), MagicMock(returncode=0)]
        ) as run:
            app._repair_mycomp_funnel()

        off, on = [call.args[0] for call in run.call_args_list]
        self.assertEqual(off[1:], ["funnel", "--https=443", "--set-path=/mycomp", "off"])
        self.assertIn("--set-path=/mycomp", on)
        self.assertIn("http://127.0.0.1:8645/", on)
        self.assertIn("--bg", on)
        self.assertNotIn("reset", off + on)
        self.assertNotIn("down", off + on)

    def test_autofix_toggle_persists_enabled_state(self):
        from windows import MyCompBot as app

        instance = app.MyCompBot.__new__(app.MyCompBot)
        instance.tailscale_autofix = True
        instance.tray_icon = None
        instance.next_tailscale_check = 0
        values = {"OTHER_SETTING": "preserved"}
        with patch.object(app, "_read_env", return_value=values.copy()), patch.object(app, "_write_env") as write:
            instance._toggle_tailscale_autofix()
            self.assertFalse(instance.tailscale_autofix)
            self.assertEqual(write.call_args.args[0]["MYCOMP_TAILSCALE_AUTOFIX"], "false")
            self.assertEqual(write.call_args.args[0]["OTHER_SETTING"], "preserved")
            instance._toggle_tailscale_autofix()
            self.assertTrue(instance.tailscale_autofix)
            self.assertEqual(write.call_args.args[0]["MYCOMP_TAILSCALE_AUTOFIX"], "true")

    def test_remote_commander_autostart_toggle_persists_without_overwriting_settings(self):
        from windows import MyCompBot as app

        instance = app.MyCompBot.__new__(app.MyCompBot)
        instance.remote_commander_autostart = MagicMock()
        instance.remote_commander_autostart.get.return_value = False
        instance.remote_commander_autostart_enabled = True
        instance.tray_icon = None
        values = {"OTHER_SETTING": "preserved"}
        with patch.object(app, "_read_env", return_value=values.copy()), patch.object(app, "_write_env") as write:
            instance._toggle_remote_commander_autostart()

        self.assertFalse(instance.remote_commander_autostart_enabled)
        self.assertEqual(write.call_args.args[0]["MYCOMP_REMOTE_DESKTOP_COMMANDER_AUTOSTART"], "false")
        self.assertEqual(write.call_args.args[0]["OTHER_SETTING"], "preserved")

    def test_remote_commander_start_reuses_existing_agent(self):
        from windows import MyCompBot as app

        instance = app.MyCompBot.__new__(app.MyCompBot)
        instance.remote_commander_process = None
        instance.remote_commander_log = None
        instance.remote_commander_status = MagicMock()
        instance.remote_commander_pid = None
        with patch.object(app, "_remote_commander_pid", return_value=12744), patch.object(app.subprocess, "Popen") as popen:
            instance._start_remote_commander()

        self.assertEqual(instance.remote_commander_pid, 12744)
        instance.remote_commander_status.set.assert_called_once_with("Already running (PID 12744)")
        popen.assert_not_called()

    def test_remote_commander_start_uses_requested_npx_command(self):
        from windows import MyCompBot as app

        instance = app.MyCompBot.__new__(app.MyCompBot)
        instance.remote_commander_process = None
        instance.remote_commander_log = None
        instance.remote_commander_status = MagicMock()
        instance.remote_commander_pid = None
        fake_log = MagicMock()
        fake_process = MagicMock(pid=24680)
        with patch.object(app, "_remote_commander_pid", return_value=None), patch.object(app.shutil, "which", return_value=r"C:\Program Files\nodejs\npx.cmd"), patch.object(app, "APP_DATA") as app_data, patch.object(app.subprocess, "Popen", return_value=fake_process) as popen:
            app_data.mkdir = MagicMock()
            app_data.__truediv__.return_value.open.return_value = fake_log
            instance._start_remote_commander()

        command = popen.call_args.args[0]
        self.assertIn("-y", command)
        self.assertIn("@wonderwhy-er/desktop-commander@latest", command)
        self.assertTrue(command.endswith(" remote"))
        self.assertEqual(instance.remote_commander_process, fake_process)
        self.assertEqual(instance.remote_commander_pid, 24680)


if __name__ == "__main__":
    unittest.main()
