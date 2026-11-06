import asyncio
import unittest

from mycomp_bot_engine.tool_queue import ToolQueue, normalize_tool_name


class ToolQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_names_short_full_and_invalid(self):
        for spelling in ("api", "mycomp.api", "mcp__mycomp_bot__api", "tools/api"):
            self.assertEqual(normalize_tool_name(spelling), "api")
        with self.assertRaises(ValueError):
            normalize_tool_name("unsafe_unknown_tool")

    async def test_duplicate_skips_without_executing_runner(self):
        q = ToolQueue()
        entered, release = asyncio.Event(), asyncio.Event()
        executions = 0

        async def slow():
            nonlocal executions
            executions += 1
            entered.set()
            await release.wait()
            return {"status": "completed", "results": [42], "changed": True}

        first = asyncio.create_task(q.execute("alice", "api", slow))
        await entered.wait()
        duplicate = await q.execute("alice", "mcp__mycomp__api", slow)
        self.assertEqual(duplicate["status"], "skipped")
        self.assertEqual(duplicate["results"], [])
        self.assertEqual(executions, 1)
        release.set()
        self.assertEqual((await first)["results"], [42])
        self.assertFalse(q.is_running("alice", "api"))

    async def test_latest_result_returned_during_subsequent_run(self):
        q = ToolQueue()
        await q.execute("alice", "api", lambda: asyncio.sleep(0, {"status": "completed", "results": ["old"]}))
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow():
            entered.set()
            await release.wait()
            return {"status": "completed", "results": ["new"]}

        task = asyncio.create_task(q.execute("alice", "api", slow))
        await entered.wait()
        duplicate = await q.execute("alice", "api", slow)
        self.assertEqual(duplicate["status"], "skipped")
        self.assertEqual(duplicate["results"], ["old"])
        release.set()
        self.assertEqual((await task)["results"], ["new"])

    async def test_separate_user_and_tool_are_concurrent(self):
        q = ToolQueue()
        entered = set()
        release = asyncio.Event()

        async def slow(key):
            entered.add(key)
            await release.wait()
            return {"status": "completed", "results": [key]}

        tasks = [
            asyncio.create_task(q.execute("alice", "api", lambda key=k: slow(key)))
            for k in ()
        ]
        tasks += [
            asyncio.create_task(q.execute(user, tool, lambda key=label: slow(key)))
            for user, tool, label in (("alice", "api", "a-api"), ("bob", "api", "b-api"), ("alice", "shell", "a-shell"))
        ]
        for _ in range(100):
            if len(entered) == 3:
                break
            await asyncio.sleep(0.001)
        self.assertEqual(len(entered), 3)
        release.set()
        results = await asyncio.gather(*tasks)
        self.assertEqual(len(results), 3)

    async def test_failed_and_cancelled_jobs_do_not_leave_stuck_slot(self):
        q = ToolQueue()
        async def fail():
            raise RuntimeError("expected failure")
        with self.assertRaises(RuntimeError):
            await q.execute("alice", "api", fail)
        self.assertFalse(q.is_running("alice", "api"))
        started, release = asyncio.Event(), asyncio.Event()

        async def slow():
            started.set()
            await release.wait()
            return {"status": "completed", "results": [1]}

        first = asyncio.create_task(q.execute("alice", "api", slow))
        await started.wait()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertTrue(q.is_running("alice", "api"), "cancelled client must not release an active worker")
        self.assertEqual((await q.execute("alice", "api", slow))["status"], "skipped")
        release.set()
        for _ in range(100):
            if not q.is_running("alice", "api"):
                break
            await asyncio.sleep(0.001)
        self.assertFalse(q.is_running("alice", "api"))
        result = await q.execute("alice", "api", lambda: asyncio.sleep(0, {"status": "completed"}))
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
