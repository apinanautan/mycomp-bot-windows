import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mycomp_bot_engine.capabilities import CapabilityRegistry
from mycomp_bot_engine.database import Database


class CapabilityRuntimeTests(unittest.TestCase):
    def test_upsert_install_upgrade_and_failed_upgrade_is_atomic(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = Database(root / "state")
            registry = CapabilityRegistry(root / "capabilities", database)
            descriptor = {"version": "1.0.0", "description": "Return the installed version"}
            version_one = "def execute(payload): return {'version': 1}\ndef self_test(): return True\n"
            installed = registry.manage("upsert", "demo", version_one, descriptor)
            self.assertEqual(installed["change"], "installed")
            self.assertEqual(registry.execute("demo", {}), {"version": 1})

            version_two = "def execute(payload): return {'version': 2}\ndef self_test(): return True\n"
            updated = registry.manage("upsert", "demo", version_two, {**descriptor, "version": "2.0.0"})
            self.assertEqual(updated["change"], "updated")
            self.assertEqual(registry.execute("demo", {}), {"version": 2})
            reopened = CapabilityRegistry(root / "capabilities", database)
            discovered = reopened.search_metadata()
            self.assertEqual(discovered[0]["name"], "demo")
            self.assertEqual(discovered[0]["version"], "2.0.0")
            self.assertEqual(discovered[0]["description"], descriptor["description"])

            failing = "def execute(payload): return {'version': 3}\ndef self_test(): return False\n"
            with self.assertRaisesRegex(ValueError, "self-test returned false"):
                registry.manage("upsert", "demo", failing, {**descriptor, "version": "3.0.0"})
            self.assertEqual(registry.execute("demo", {}), {"version": 2})
            self.assertEqual((root / "capabilities" / "demo.py").read_text(), version_two)
            registry.manage("rollback", "demo")
            self.assertEqual(registry.execute("demo", {}), {"version": 1})
            registry.manage("deactivate", "demo")
            with self.assertRaises(PermissionError):
                registry.execute("demo", {})
            database.close()

    def test_upsert_rejects_invalid_contract_without_installing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = Database(root / "state")
            registry = CapabilityRegistry(root / "capabilities", database)
            with self.assertRaisesRegex(ValueError, "descriptor"):
                registry.manage("upsert", "demo", "def execute(payload): return {}\ndef self_test(): return True\n", {"version": "1"})
            with self.assertRaisesRegex(ValueError, "signature"):
                registry.manage("upsert", "demo", "def execute(): return {}\ndef self_test(): return True\n", {"version": "1", "description": "demo"})
            self.assertEqual(registry.search(), [])
            database.close()

    def test_excessive_output_is_stopped_at_streaming_limit(self):
        source = b"""\
import sys
def execute(payload):
    sys.stdout.write('x' * 100_000)
    sys.stdout.flush()
    return {}
def self_test(): return True
"""
        with patch("mycomp_bot_engine.capabilities._OUTPUT_LIMIT_BYTES", 1_024):
            with self.assertRaisesRegex(ValueError, "output exceeds limit"):
                CapabilityRegistry._run(source, "large_output", "execute", {})

    def test_timeout_kills_descendant_process_group(self):
        with tempfile.TemporaryDirectory() as temp:
            pid_path = Path(temp) / "child.pid"
            source = b"""\
import subprocess, sys, time
def execute(payload):
    child = "import os,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open(%r, 'w').write(str(os.getpid())); time.sleep(60)" % payload['pid_path']
    subprocess.Popen([sys.executable, '-c', child])
    deadline = time.monotonic() + 2
    while not __import__('os').path.exists(payload['pid_path']) and time.monotonic() < deadline:
        time.sleep(.01)
    time.sleep(60)
def self_test(): return True
"""
            with (
                patch("mycomp_bot_engine.capabilities._RUN_TIMEOUT_SECONDS", 0.3),
                patch("mycomp_bot_engine.capabilities._TERMINATE_GRACE_SECONDS", 0.1),
            ):
                with self.assertRaisesRegex(ValueError, "timed out"):
                    CapabilityRegistry._run(source, "timeout_child", "execute", {"pid_path": str(pid_path)})

            self.assertTrue(pid_path.is_file(), "descendant did not start before timeout")
            child_pid = int(pid_path.read_text())
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                self.fail("descendant survived capability timeout")

    def test_capability_metadata_is_self_describing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = Database(root / "state")
            registry = CapabilityRegistry(root / "capabilities", database)
            descriptor = {
                "version": "1.2.0",
                "description": "Self describing demo",
                "input_schema": {"type": "object", "properties": {"value": {"type": "integer"}}},
                "output_schema": {"type": "object"},
                "examples": [{"value": 1}],
                "permissions": ["accessibility"],
                "side_effects": "ui_control",
                "supports_dry_run": True,
                "default_timeout_seconds": 12,
                "execution_modes": ["foreground", "background", "auto"],
                "tags": ["macos"],
            }
            source = "def execute(payload): return payload\ndef self_test(): return True\n"
            registry.manage("upsert", "described", source, descriptor)
            found = registry.search_metadata()[0]
            self.assertEqual(found["input_schema"], descriptor["input_schema"])
            self.assertEqual(found["permissions"], ["accessibility"])
            self.assertEqual(found["default_timeout_seconds"], 12)
            database.close()

    def test_capability_background_job_uses_job_control(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = Database(root / "state")
            registry = CapabilityRegistry(root / "capabilities", database)
            source = "import time\ndef execute(payload): time.sleep(.15); return {'value': payload['value']}\ndef self_test(): return True\n"
            descriptor = {
                "version": "1.0.0",
                "description": "Background demo",
                "default_timeout_seconds": 2,
            }
            registry.manage("upsert", "background_demo", source, descriptor)
            launched = registry.execute("background_demo", {"value": 7, "__execution": {"mode": "background"}})
            self.assertEqual(launched["state"], "running")
            result = registry.control("wait", launched["job_id"], timeout_seconds=2)
            self.assertEqual(result["state"], "finished")
            self.assertEqual(result["result"], {"value": 7})
            database.close()

    def test_capability_execution_does_not_write_bytecode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = Database(root / "state")
            registry = CapabilityRegistry(root / "capabilities", database)
            source = (
                "from pathlib import Path\n"
                "def execute(payload):\n"
                "    Path('helper.py').write_text('value = 7')\n"
                "    import sys; sys.path.insert(0, '.')\n"
                "    import helper\n"
                "    return {'value': helper.value, 'pycache_exists': Path('__pycache__').exists()}\n"
                "def self_test(): return True\n"
            )
            registry.manage("upsert", "no_bytecode", source, {"version": "1.0.0", "description": "No bytecode test"})
            result = registry.execute("no_bytecode", {})
            self.assertEqual(result["value"], 7)
            self.assertFalse(result["pycache_exists"])
            database.close()


if __name__ == "__main__":
    unittest.main()
