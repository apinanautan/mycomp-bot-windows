import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from mycomp_bot_engine.capabilities import CapabilityRegistry
from mycomp_bot_engine.config import Settings
from mycomp_bot_engine.database import Database
from mycomp_bot_engine.server import _sync_maintained_capabilities


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "capability_sources"


class MaintainedCapabilityTests(unittest.TestCase):
    def test_manifest_covers_every_maintained_python_source(self):
        manifest = json.loads((SOURCES / "manifest.json").read_text())
        sources = {path.stem for path in SOURCES.glob("*.py") if not path.name.startswith("_")}
        self.assertEqual(set(manifest), sources)

    def test_each_maintained_source_self_test_passes(self):
        for path in sorted(SOURCES.glob("*.py")):
            spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertTrue(module.self_test(), path.name)

    def test_startup_sync_installs_and_updates_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            maintained = temp_path / "maintained"
            maintained.mkdir()
            source = "def execute(payload): return {'ok': True}\ndef self_test(): return True\n"
            (maintained / "demo.py").write_text(source)
            descriptor = {
                "version": "1.0.0",
                "description": "demo maintained capability",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "examples": [],
                "permissions": [],
                "side_effects": "none",
                "supports_dry_run": False,
                "default_timeout_seconds": 30,
                "execution_modes": ["foreground"],
                "tags": ["test"],
            }
            (maintained / "manifest.json").write_text(json.dumps({"demo": descriptor}))
            database = Database(temp_path / "state")
            try:
                registry = CapabilityRegistry(temp_path / "caps", database)
                settings = Settings(
                    host="127.0.0.1", port=8645, allowed_roots=(), allow_shell=False,
                    allowed_executables=(), data_dir=temp_path / "state",
                    capability_dir=temp_path / "caps", redirect_uris=frozenset(),
                    owner_consent_token=None, maintained_capability_dir=maintained,
                )
                first = _sync_maintained_capabilities(settings, registry)
                self.assertEqual(first[0]["state"], "updated")
                self.assertEqual(registry.execute("demo", {}), {"ok": True})
                second = _sync_maintained_capabilities(settings, registry)
                self.assertEqual(second[0]["state"], "current")
                descriptor["version"] = "1.1.0"
                (maintained / "manifest.json").write_text(json.dumps({"demo": descriptor}))
                third = _sync_maintained_capabilities(settings, registry)
                self.assertEqual(third[0]["state"], "updated")
                self.assertEqual(registry.search_metadata()[0]["version"], "1.1.0")
            finally:
                database.close()


if __name__ == "__main__":
    unittest.main()
