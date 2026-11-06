import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP
from mycomp_bot_engine.config import Settings
from mycomp_bot_engine.server import create_app
from mycomp_bot_engine.database import Database


class ToolConcurrencyTests(unittest.TestCase):
    def test_blocking_api_does_not_stall_event_loop(self):
        functions = {}
        original = FastMCP.add_tool
        databases = []
        initialize = Database.__init__

        def track(database, *args, **kwargs):
            initialize(database, *args, **kwargs)
            databases.append(database)

        def capture(server, fn, *args, **kwargs):
            functions[fn.__name__] = fn
            return original(server, fn, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(host="127.0.0.1", port=8645, allow_shell=False, allowed_executables=frozenset(), redirect_uris=frozenset(), owner_consent_token="test-owner-consent-token-at-least-32-chars", allowed_roots=(root,), data_dir=root / "data", capability_dir=root / "caps")
            with patch.object(FastMCP, "add_tool", capture), patch.object(Database, "__init__", track):
                create_app(settings)

            def slow_validation(*args, **kwargs):
                time.sleep(0.15)
                raise ValueError("probe complete")

            async def check():
                task = asyncio.create_task(functions["api"](url="https://example.com"))
                await asyncio.sleep(0.02)
                self.assertFalse(task.done(), "API blocked event loop")
                result = await task
                self.assertEqual(result["error"]["message"], "probe complete")

            with patch("mycomp_bot_engine.server.urllib.request.OpenerDirector.open", slow_validation):
                try:
                    asyncio.run(check())
                finally:
                    for database in databases:
                        database.close()

    def test_same_user_duplicate_api_is_skipped_and_tool_slot_clears(self):
        functions = {}
        original = FastMCP.add_tool
        databases = []
        initialize = Database.__init__

        def track(database, *args, **kwargs):
            initialize(database, *args, **kwargs)
            databases.append(database)

        def capture(server, fn, *args, **kwargs):
            functions[fn.__name__] = fn
            return original(server, fn, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(host="127.0.0.1", port=8645, allow_shell=False,
                                allowed_executables=frozenset(), redirect_uris=frozenset(),
                                owner_consent_token="test-owner-consent-token-at-least-32-chars",
                                allowed_roots=(root,), data_dir=root / "data", capability_dir=root / "caps")
            with patch.object(FastMCP, "add_tool", capture), patch.object(Database, "__init__", track):
                app = create_app(settings)
            entered, release = asyncio.Event(), asyncio.Event()
            calls = []

            def slow_validation(*args, **kwargs):
                calls.append(1)
                # The function runs in a worker thread, not the event loop.
                import threading
                worker_entered.set()
                worker_release.wait(timeout=3)
                raise ValueError("expected probe")

            worker_entered = __import__("threading").Event()
            worker_release = __import__("threading").Event()

            async def check():
                first = asyncio.create_task(functions["api"](url="https://example.com"))
                self.assertTrue(await asyncio.to_thread(worker_entered.wait, 3))
                other = await functions["api"](url="https://example.com")
                self.assertEqual(other["status"], "skipped")
                self.assertEqual(len(calls), 1)
                worker_release.set()
                self.assertEqual((await first)["status"], "failed")
                next_result = await functions["api"](url="https://example.com")
                self.assertEqual(next_result["status"], "failed")
                self.assertEqual(len(calls), 2)

            with patch("mycomp_bot_engine.server.urllib.request.OpenerDirector.open", slow_validation):
                try:
                    asyncio.run(check())
                finally:
                    worker_release.set()
                    for database in databases:
                        database.close()


if __name__ == "__main__":
    unittest.main()
