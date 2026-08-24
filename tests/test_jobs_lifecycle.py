import tempfile
import threading
import time
import unittest
import os
from pathlib import Path

from mycomp_bot_engine.database import Database
from mycomp_bot_engine.jobs import Shell


class ShellLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "root"
        self.root.mkdir()
        self.database = Database(Path(self.temp.name) / "state")

    def tearDown(self):
        self.database.close()
        self.temp.cleanup()

    def test_background_limit_and_shutdown(self):
        shell = Shell(
            True,
            (Path("/bin/sleep").resolve(),),
            self.database,
            128,
            max_background_jobs=1,
        )
        job = shell.run("background", ["/bin/sleep", "30"], self.root)
        with self.assertRaises(RuntimeError):
            shell.run("background", ["/bin/sleep", "30"], self.root)
        shell.shutdown()
        self.assertEqual(shell.control("status", job["job_id"])["state"], "cancelled")

    def test_finished_job_is_not_resumable(self):
        shell = Shell(True, (Path("/bin/echo").resolve(),), self.database, 128)
        job = shell.run("background", ["/bin/echo", "done"], self.root)
        for _ in range(50):
            if shell.control("status", job["job_id"])["state"] == "finished":
                break
            time.sleep(0.01)
        with self.assertRaises(ValueError):
            shell.control("resume", job["job_id"])

    def test_shutdown_kills_term_ignoring_descendant_after_leader_exits(self):
        script = (
            "import os,signal,time\n"
            "pid=os.fork()\n"
            "if pid: raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "open('child.pid','w').write(str(os.getpid()))\n"
            "time.sleep(30)\n"
        )
        shell = Shell(True, (Path("/usr/bin/python3").resolve(),), self.database, 128)
        job = shell.run("background", ["/usr/bin/python3", "-c", script], self.root)
        child_pid_file = self.root / "child.pid"
        child_pid_text = ""
        for _ in range(200):
            if child_pid_file.exists():
                child_pid_text = child_pid_file.read_text().strip()
                if child_pid_text:
                    break
            time.sleep(0.01)
        self.assertTrue(child_pid_text, "child PID was not durably written")
        child_pid = int(child_pid_text)
        shell.shutdown()
        with self.assertRaises(ProcessLookupError):
            os.kill(child_pid, 0)
        self.assertEqual(shell.control("status", job["job_id"])["state"], "cancelled")

    def test_foreground_timeout_is_resumable_with_original_specification(self):
        shell = Shell(
            True,
            (Path("/bin/sleep").resolve(),),
            self.database,
            128,
            foreground_timeout=0.02,
        )
        with self.assertRaises(TimeoutError):
            shell.run("foreground", ["/bin/sleep", "0.1"], self.root)
        timed_out = self.database.connection.execute("SELECT id FROM jobs WHERE state = 'timed_out'").fetchone()[0]
        stored = shell.control("status", timed_out)
        self.assertEqual(stored["argv"], [str(Path("/bin/sleep").resolve()), "0.1"])
        self.assertEqual(stored["cwd"], str(self.root.resolve()))
        resumed = shell.control("resume", timed_out)
        self.assertTrue(resumed["resumed"])
        shell.shutdown()

    def test_subprocess_environment_excludes_parent_secrets(self):
        previous = os.environ.get("MYCOMP_OWNER_CONSENT_TOKEN")
        os.environ["MYCOMP_OWNER_CONSENT_TOKEN"] = "must-not-leak"
        try:
            shell = Shell(True, (Path("/usr/bin/env").resolve(),), self.database, 4096)
            result = shell.run("foreground", ["/usr/bin/env"], self.root)
        finally:
            if previous is None: os.environ.pop("MYCOMP_OWNER_CONSENT_TOKEN", None)
            else: os.environ["MYCOMP_OWNER_CONSENT_TOKEN"] = previous
        self.assertNotIn("MYCOMP_OWNER_CONSENT_TOKEN", result["stdout"])

    def test_unrestricted_shell_bypasses_allowlist_and_strips_mycomp_env(self):
        previous = os.environ.get("MYCOMP_OWNER_CONSENT_TOKEN")
        os.environ["MYCOMP_OWNER_CONSENT_TOKEN"] = "must-not-leak"
        marker = "MYCOMP_FULL_CONTROL_MARKER=present"
        os.environ["MYCOMP_FULL_CONTROL_MARKER"] = "present"
        try:
            # Empty allowlist would block restricted mode; unrestricted may still run /bin/echo.
            shell = Shell(True, (), self.database, 4096)
            with self.assertRaises(PermissionError):
                shell.run("foreground", ["/bin/echo", "blocked"], self.root)
            result = shell.run("foreground", ["/bin/echo", "allowed"], self.root, unrestricted=True)
            self.assertEqual(result["state"], "finished")
            self.assertIn("allowed", result["stdout"])
            env_result = shell.run("foreground", ["/usr/bin/env"], self.root, unrestricted=True)
            self.assertNotIn("MYCOMP_OWNER_CONSENT_TOKEN", env_result["stdout"])
            self.assertNotIn(marker, env_result["stdout"])
            self.assertIn("PATH=", env_result["stdout"])
        finally:
            os.environ.pop("MYCOMP_FULL_CONTROL_MARKER", None)
            if previous is None:
                os.environ.pop("MYCOMP_OWNER_CONSENT_TOKEN", None)
            else:
                os.environ["MYCOMP_OWNER_CONSENT_TOKEN"] = previous

    def test_unrestricted_shell_skips_sudo_owner_gate(self):
        shell = Shell(True, (Path("/usr/bin/sudo").resolve(), Path("/bin/echo").resolve()), self.database, 4096)
        gated = shell.run("foreground", ["/usr/bin/sudo", "-n", "/bin/echo", "need-approval"], self.root)
        self.assertEqual(gated["state"], "approval_required")
        launched = shell.run(
            "background",
            ["/usr/bin/sudo", "-n", "/bin/echo", "full"],
            self.root,
            unrestricted=True,
        )
        self.assertEqual(launched["state"], "running")
        shell.shutdown()

    def test_auto_mode_returns_job_and_wait_collects_result(self):
        python = Path("/usr/bin/python3").resolve()
        shell = Shell(True, (python,), self.database, 4096, auto_wait_seconds=0.01)
        job = shell.run("auto", [str(python), "-c", "import time; time.sleep(.2); print('done')"], self.root)
        self.assertEqual(job["state"], "running")
        finished = shell.control("wait", job["job_id"], timeout_seconds=2)
        self.assertEqual(finished["state"], "finished")
        self.assertEqual(finished["stdout"], "done\n")

    def test_shell_output_controls_return_only_requested_tail(self):
        python = Path("/usr/bin/python3").resolve()
        shell = Shell(True, (python,), self.database, 4096)
        result = shell.run(
            "foreground",
            [str(python), "-c", "import sys; print('one'); print('two'); print('three'); print('error', file=sys.stderr)"],
            self.root,
            tail_lines=1,
            include_stderr=False,
        )
        self.assertEqual(result["stdout"], "three\n")
        self.assertTrue(result["stdout_truncated"])
        self.assertNotIn("stderr", result)

    def _orphan_script(self, pid_name: str) -> str:
        return (
            "import os,signal,time\n"
            "pid=os.fork()\n"
            "if pid:\n"
            " time.sleep(.1)\n"
            " raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            f"open({pid_name!r},'w').write(str(os.getpid()))\n"
            "print('child inherited stdout', flush=True)\n"
            "time.sleep(30)\n"
        )

    def _assert_pid_gone(self, path: Path) -> None:
        pid = int(path.read_text())
        for _ in range(100):
            try: os.kill(pid, 0)
            except ProcessLookupError: return
            time.sleep(0.01)
        self.fail(f"descendant process {pid} survived")

    def test_foreground_normal_leader_exit_kills_pipe_holding_descendant(self):
        shell = Shell(True, (Path("/usr/bin/python3").resolve(),), self.database, 4096, foreground_timeout=5)
        pid_file = self.root / "foreground-child.pid"
        started = time.monotonic()
        result = shell.run("foreground", ["/usr/bin/python3", "-c", self._orphan_script(pid_file.name)], self.root)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(result["state"], "finished")
        self.assertIn("child inherited stdout", result["stdout"])
        self._assert_pid_gone(pid_file)

    def test_background_normal_leader_exit_kills_pipe_holding_descendant(self):
        shell = Shell(True, (Path("/usr/bin/python3").resolve(),), self.database, 4096, background_timeout=5)
        pid_file = self.root / "background-child.pid"
        job = shell.run("background", ["/usr/bin/python3", "-c", self._orphan_script(pid_file.name)], self.root)
        for _ in range(600):
            status = shell.control("status", job["job_id"])
            if status["state"] == "finished": break
            time.sleep(0.01)
        else: self.fail("background job did not finish")
        self.assertIn("child inherited stdout", status["stdout"])
        self._assert_pid_gone(pid_file)

    def test_shutdown_tracks_and_waits_for_foreground_cleanup(self):
        shell = Shell(True, (Path("/bin/sleep").resolve(),), self.database, 128, foreground_timeout=30)
        outcome = []
        worker = threading.Thread(
            target=lambda: self._record_foreground_outcome(shell, outcome),
            daemon=True,
        )
        worker.start()
        for _ in range(100):
            with shell._lock:
                if shell.processes: break
            time.sleep(0.01)
        shell.shutdown()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcome, ["cancelled"])
        state = self.database.connection.execute("SELECT state FROM jobs").fetchone()[0]
        self.assertEqual(state, "cancelled")

    def _record_foreground_outcome(self, shell: Shell, outcome: list[str]) -> None:
        try:
            shell.run("foreground", ["/bin/sleep", "30"], self.root)
        except RuntimeError as error:
            if str(error) == "foreground command was cancelled":
                outcome.append("cancelled")
            else:
                raise


if __name__ == "__main__":
    unittest.main()
