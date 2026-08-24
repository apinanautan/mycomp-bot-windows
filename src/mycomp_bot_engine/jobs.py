from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .database import Database


class Shell:
    def __init__(
        self,
        enabled: bool,
        executables: tuple[Path, ...],
        database: Database,
        max_output: int,
        max_background_jobs: int = 4,
        background_timeout: int = 900,
        foreground_timeout: float = 30,
        shell_path: str = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        auto_wait_seconds: float = 5,
    ) -> None:
        self.enabled, self.executables, self.database, self.max_output = enabled, executables, database, max_output
        self.max_background_jobs = max_background_jobs
        self.background_timeout = background_timeout
        self.foreground_timeout = foreground_timeout
        self.shell_path = shell_path
        self.auto_wait_seconds = auto_wait_seconds
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self._output: dict[str, dict[str, bytearray]] = {}
        self._output_truncated: dict[str, dict[str, bool]] = {}
        self._finishers: dict[str, threading.Thread] = {}
        self._foreground_done: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._shutdown = False
        self._background_slots = threading.BoundedSemaphore(max_background_jobs)
        with self.database.transaction():
            rows = self.database.connection.execute("SELECT id, payload FROM jobs WHERE state IN ('starting', 'running')").fetchall()
            for job_id, raw_payload in rows:
                import json
                payload = json.loads(raw_payload)
                payload["error"] = "engine restarted before this job could be reconciled"
                self.database.connection.execute("UPDATE jobs SET state = 'interrupted', payload = ? WHERE id = ?", (json.dumps(payload), job_id))
            self.database.connection.commit()

    def _resolve_executable(self, raw: str, *, unrestricted: bool) -> Path:
        if unrestricted:
            candidate = Path(raw).expanduser()
            if candidate.is_absolute():
                executable = candidate.resolve(strict=True)
            else:
                resolved = shutil.which(raw, path=self.shell_path)
                if resolved is None:
                    raise PermissionError(f"executable not found on MYCOMP_SHELL_PATH: {raw}")
                executable = Path(resolved).resolve(strict=True)
            info = executable.stat()
            if os.name != "nt" and (not (info.st_mode & 0o111) or not os.access(executable, os.X_OK)):
                raise PermissionError("resolved path is not executable")
            return executable

        # Elevated/normal keep the exact allowlist: absolute/cwd-resolved path only.
        executable = Path(raw).expanduser().resolve(strict=True)
        if executable not in self.executables or executable.is_symlink():
            raise PermissionError("executable is not in MYCOMP_ALLOWED_EXECUTABLES")
        info = executable.stat()
        if os.name != "nt" and not info.st_mode & 0o111:
            raise PermissionError("configured executable is not executable")
        if os.name != "nt" and (info.st_uid != 0 or info.st_mode & 0o022):
            raise PermissionError("allowed executable must be root-owned and not group/world writable")
        return executable

    def _check(self, argv: list[str], cwd: Path, *, unrestricted: bool = False) -> tuple[list[str], Path]:
        if not self.enabled:
            raise PermissionError("shell is disabled: set MYCOMP_ALLOW_SHELL=true")
        if not argv:
            raise PermissionError("an executable is required")
        executable = self._resolve_executable(str(argv[0]), unrestricted=unrestricted)
        resolved_cwd = Path(cwd).expanduser().resolve(strict=True)
        if not resolved_cwd.is_dir():
            raise NotADirectoryError(resolved_cwd)
        return [str(executable), *argv[1:]], resolved_cwd

    def _subprocess_env(self, *, unrestricted: bool) -> dict[str, str]:
        if unrestricted:
            # Inherit the owner login environment so real desktop/CLI tools work, but
            # never export MyComp control-plane secrets into child processes.
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("MYCOMP_")
            }
            env["PATH"] = self.shell_path
            env.setdefault("LANG", "en_US.UTF-8")
            env.setdefault("LC_ALL", "en_US.UTF-8")
            return env
        return {"PATH": self.shell_path, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}

    def _popen(self, argv: list[str], cwd: Path, *, unrestricted: bool = False) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0,
            env=self._subprocess_env(unrestricted=unrestricted),
        )

    @staticmethod
    def _group_exists(process: subprocess.Popen[bytes]) -> bool:
        if os.name == "nt":
            return process.poll() is None
        try:
            os.killpg(process.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    @classmethod
    def _kill_group(cls, process: subprocess.Popen[bytes]) -> None:
        if os.name == "nt":
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
            completed = subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            if process.poll() is None:
                raise RuntimeError(f"Windows process tree could not be reaped (taskkill={completed.returncode})")
            return
        try: os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        deadline = time.monotonic() + 2
        while cls._group_exists(process) and time.monotonic() < deadline:
            process.poll()
            time.sleep(0.02)
        if cls._group_exists(process):
            try: os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError): pass
        try: process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=2)
        deadline = time.monotonic() + 2
        while cls._group_exists(process) and time.monotonic() < deadline: time.sleep(0.02)
        if cls._group_exists(process): raise RuntimeError("process group could not be reaped")

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            with self._lock:
                self._shutdown = True
                active = list(self.processes.items())
        for job_id, process in active:
            stored = self.database.job(job_id)
            if stored:
                payload = {key: value for key, value in stored.items() if key not in {"id", "state"}}
                payload.update({"cancelled": True, "error": "engine shutdown", **self._snapshot(job_id)})
                self.database.transition_job(job_id, {"starting", "running"}, "cancelled", payload)
            self._kill_group(process)
        with self._lock:
            finishers = list(self._finishers.values())
            foreground_done = list(self._foreground_done.values())
        for thread in finishers:
            thread.join(timeout=8)
            if thread.is_alive(): raise RuntimeError("background job cleanup did not finish")
        for done in foreground_done:
            if not done.wait(timeout=8): raise RuntimeError("foreground job cleanup did not finish")

    def _append(self, job_id: str, key: str, chunk: bytes) -> None:
        with self._lock:
            output = self._output[job_id][key]
            output.extend(chunk)
            if len(output) > self.max_output:
                del output[:-self.max_output]
                self._output_truncated[job_id][key] = True

    def _snapshot(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            output = self._output.get(job_id, {})
            truncated = self._output_truncated.get(job_id, {})
            result: dict[str, Any] = {key: value.decode("utf-8", errors="replace") for key, value in output.items()}
            for key in ("stdout", "stderr"):
                if key in result:
                    result[f"{key}_truncated"] = bool(truncated.get(key, False))
            return result

    def _format_output(
        self,
        payload: dict[str, Any],
        *,
        max_output_bytes: int | None = None,
        tail_lines: int | None = None,
        include_stdout: bool = True,
        include_stderr: bool = True,
    ) -> dict[str, Any]:
        result = dict(payload)
        limit = self.max_output if max_output_bytes is None else min(max(int(max_output_bytes), 0), self.max_output)
        if tail_lines is not None:
            tail_lines = min(max(int(tail_lines), 0), 10_000)
        for key, include in (("stdout", include_stdout), ("stderr", include_stderr)):
            if not include:
                result.pop(key, None); result.pop(f"{key}_truncated", None)
                continue
            if key not in result: continue
            text = str(result[key])
            truncated = bool(result.get(f"{key}_truncated", False))
            if tail_lines is not None:
                lines = text.splitlines()
                if len(lines) > tail_lines:
                    text = "\n".join(lines[-tail_lines:])
                    if str(result[key]).endswith("\n") and tail_lines: text += "\n"
                    truncated = True
                elif tail_lines == 0 and text:
                    text = ""; truncated = True
            encoded = text.encode("utf-8")
            if len(encoded) > limit:
                text = encoded[-limit:].decode("utf-8", errors="replace") if limit else ""
                truncated = True
            result[key] = text
            result[f"{key}_truncated"] = truncated
        return result

    @staticmethod
    def _bounded_timeout(value: float | None, default: float, maximum: float) -> float:
        selected = default if value is None else float(value)
        if selected < 0: raise ValueError("timeout_seconds must not be negative")
        return min(selected, maximum)

    def _start_background(
        self,
        argv: list[str],
        cwd: Path,
        resumed_from: str | None = None,
        *,
        unrestricted: bool = False,
    ) -> dict[str, Any]:
        with self._lifecycle_lock:
            return self._start_background_locked(argv, cwd, resumed_from, unrestricted=unrestricted)

    def _start_background_locked(
        self,
        argv: list[str],
        cwd: Path,
        resumed_from: str | None = None,
        *,
        unrestricted: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            if self._shutdown: raise RuntimeError("shell is shutting down")
        if not self._background_slots.acquire(blocking=False): raise RuntimeError("background job limit reached")
        job_id = uuid.uuid4().hex
        self.database.save_job(job_id, "starting", {
            "argv": argv, "cwd": str(cwd), "started": time.time(), "resumed_from": resumed_from,
            "unrestricted": unrestricted,
        })
        try:
            checked, checked_cwd = self._check(argv, cwd, unrestricted=unrestricted)
            process = self._popen(checked, checked_cwd, unrestricted=unrestricted)
        except BaseException as error:
            self.database.transition_job(job_id, {"starting"}, "failed", {"argv": argv, "cwd": str(cwd), "error": str(error)})
            self._background_slots.release()
            raise
        with self._lock:
            self.processes[job_id] = process
            self._output[job_id] = {"stdout": bytearray(), "stderr": bytearray()}
            self._output_truncated[job_id] = {"stdout": False, "stderr": False}
        self.database.transition_job(job_id, {"starting"}, "running", {
            "argv": checked, "cwd": str(checked_cwd), "started": time.time(), "resumed_from": resumed_from,
            "unrestricted": unrestricted,
        })

        def reader(stream: Any, key: str) -> None:
            for chunk in iter(lambda: stream.read(4096), b""): self._append(job_id, key, chunk)
            stream.close()

        readers = [threading.Thread(target=reader, args=(stream, key), daemon=True) for stream, key in ((process.stdout, "stdout"), (process.stderr, "stderr"))]
        for thread in readers: thread.start()

        def finish() -> None:
            group_cleaned = False
            try:
                timed_out = False
                try: code = process.wait(timeout=self.background_timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True; code = process.returncode
                self._kill_group(process)
                group_cleaned = True
                if code is None: code = process.returncode
                for thread in readers:
                    thread.join(timeout=3)
                    if thread.is_alive(): raise RuntimeError("background output reader did not finish")
                payload = {"argv": checked, "cwd": str(checked_cwd), "started": time.time(), "resumed_from": resumed_from, "exit_code": code, **self._snapshot(job_id)}
                self.database.transition_job(job_id, {"starting", "running"}, "timed_out" if timed_out else "finished", payload)
            finally:
                with self._lock:
                    if group_cleaned:
                        self.processes.pop(job_id, None)
                        self._output.pop(job_id, None)
                        self._output_truncated.pop(job_id, None)
                    self._finishers.pop(job_id, None)
                if group_cleaned: self._background_slots.release()

        finisher = threading.Thread(target=finish, daemon=True)
        with self._lock: self._finishers[job_id] = finisher
        finisher.start()
        return {"job_id": job_id, "state": "running"}

    @staticmethod
    def _requires_owner_approval(argv: list[str]) -> bool:
        if not argv: return False
        try: return Path(argv[0]).name == "sudo"
        except (TypeError, ValueError): return False

    def _request_owner_approval(self, mode: str, argv: list[str], cwd: Path) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        checked, checked_cwd = self._check(argv, cwd, unrestricted=False)
        payload = {
            "argv": checked, "cwd": str(checked_cwd), "requested_mode": mode, "requested": time.time(),
            "approval_kind": "sudo", "approval_scope": "once", "password_handling": "user_only",
            "reason_required": True, "unrestricted": False,
        }
        self.database.save_job(job_id, "approval_required", payload)
        return {
            "job_id": job_id, "state": "approval_required", "approval_kind": "sudo",
            "approval_scope": "once", "password_handling": "user_only", "argv": checked,
            "cwd": str(checked_cwd),
            "message": "Owner approval is required before this sudo command can run.",
        }

    def run(
        self,
        mode: str,
        argv: list[str],
        cwd: Path,
        *,
        timeout_seconds: float | None = None,
        max_output_bytes: int | None = None,
        tail_lines: int | None = None,
        include_stdout: bool = True,
        include_stderr: bool = True,
        unrestricted: bool = False,
    ) -> dict[str, Any]:
        if mode not in {"foreground", "background", "auto"}: raise ValueError("mode must be foreground, background, or auto")
        # Full control runs sudo immediately (still via sudo -n). Lower levels keep the owner gate.
        if self._requires_owner_approval(argv) and not unrestricted:
            return self._request_owner_approval(mode, argv, cwd)
        if mode in {"background", "auto"}:
            launched = self._start_background(argv, cwd, unrestricted=unrestricted)
            if mode == "background": return launched
            waited = self.control(
                "wait", launched["job_id"],
                timeout_seconds=self._bounded_timeout(timeout_seconds, self.auto_wait_seconds, 60),
                max_output_bytes=max_output_bytes, tail_lines=tail_lines,
                include_stdout=include_stdout, include_stderr=include_stderr,
                unrestricted=unrestricted,
            )
            waited["job_id"] = waited.pop("id")
            return waited

        job_id = uuid.uuid4().hex
        with self._lifecycle_lock:
            with self._lock:
                if self._shutdown: raise RuntimeError("shell is shutting down")
            self.database.save_job(job_id, "running", {
                "argv": argv, "cwd": str(cwd), "started": time.time(), "unrestricted": unrestricted,
            })
            try:
                checked, checked_cwd = self._check(argv, cwd, unrestricted=unrestricted)
                process = self._popen(checked, checked_cwd, unrestricted=unrestricted)
            except BaseException as error:
                self.database.transition_job(job_id, {"running"}, "failed", {"argv": argv, "cwd": str(cwd), "error": str(error)})
                raise
            done = threading.Event()
            with self._lock:
                self.processes[job_id] = process
                self._output[job_id] = {"stdout": bytearray(), "stderr": bytearray()}
                self._output_truncated[job_id] = {"stdout": False, "stderr": False}
                self._foreground_done[job_id] = done

        def reader(stream: Any, key: str) -> None:
            for chunk in iter(lambda: stream.read(4096), b""): self._append(job_id, key, chunk)
            stream.close()

        threads = [threading.Thread(target=reader, args=(stream, key), daemon=True) for stream, key in ((process.stdout, "stdout"), (process.stderr, "stderr"))]
        for thread in threads: thread.start()
        group_cleaned = False
        try:
            timed_out = False
            try: process.wait(timeout=self._bounded_timeout(timeout_seconds, self.foreground_timeout, 300))
            except subprocess.TimeoutExpired: timed_out = True
            self._kill_group(process)
            group_cleaned = True
            for thread in threads:
                thread.join(timeout=3)
                if thread.is_alive(): raise RuntimeError("foreground output reader did not finish")
            result = {"exit_code": process.returncode, **self._snapshot(job_id)}
            finished_payload = {
                "argv": checked, "cwd": str(checked_cwd), "unrestricted": unrestricted, **result,
            }
            if timed_out:
                self.database.transition_job(job_id, {"running"}, "timed_out", finished_payload)
                raise TimeoutError("foreground command timed out")
            transitioned = self.database.transition_job(job_id, {"running"}, "finished", finished_payload)
            if not transitioned: raise RuntimeError("foreground command was cancelled")
            return self._format_output({"job_id": job_id, "state": "finished", **result}, max_output_bytes=max_output_bytes, tail_lines=tail_lines, include_stdout=include_stdout, include_stderr=include_stderr)
        finally:
            with self._lock:
                if group_cleaned:
                    self.processes.pop(job_id, None)
                    self._output.pop(job_id, None)
                    self._output_truncated.pop(job_id, None)
                self._foreground_done.pop(job_id, None)
            done.set()

    def control(
        self,
        operation: str,
        job_id: str,
        *,
        timeout_seconds: float | None = None,
        max_output_bytes: int | None = None,
        tail_lines: int | None = None,
        include_stdout: bool = True,
        include_stderr: bool = True,
        unrestricted: bool = False,
    ) -> dict[str, Any]:
        if operation not in {"status", "logs", "result", "wait", "cancel", "resume", "approve", "deny"}: raise ValueError("unsupported job operation")
        stored = self.database.job(job_id)
        if not stored: raise KeyError("job not found")
        with self._lock:
            process = self.processes.get(job_id)
            finisher = self._finishers.get(job_id)
        job_unrestricted = bool(stored.get("unrestricted", False)) or unrestricted
        if operation == "wait":
            if stored["state"] in {"starting", "running"} and finisher:
                finisher.join(timeout=self._bounded_timeout(timeout_seconds, 20, 60))
            stored = self.database.job(job_id)
            if not stored: raise KeyError("job not found")
            with self._lock: process = self.processes.get(job_id)
            live = self._snapshot(job_id) if process and process.poll() is None else {}
            return self._format_output({"id": job_id, **{key: value for key, value in stored.items() if key != "id"}, **live}, max_output_bytes=max_output_bytes, tail_lines=tail_lines, include_stdout=include_stdout, include_stderr=include_stderr)
        if operation == "approve":
            if stored["state"] != "approval_required" or stored.get("approval_kind") != "sudo": raise ValueError("job is not awaiting sudo approval")
            argv, cwd = stored.get("argv"), stored.get("cwd")
            if not isinstance(argv, list) or not isinstance(cwd, str): raise ValueError("approval request has no executable specification")
            payload = {key: value for key, value in stored.items() if key not in {"id", "state"}}
            payload.update({"approved": True, "approved_at": time.time()})
            if not self.database.transition_job(job_id, {"approval_required"}, "approved", payload): raise RuntimeError("sudo approval request changed before approval")
            launched = self._start_background(argv, Path(cwd), resumed_from=job_id, unrestricted=job_unrestricted)
            return {**launched, "approved": True, "approval_job_id": job_id, "password_handling": "user_only"}
        if operation == "deny":
            if stored["state"] != "approval_required": raise ValueError("job is not awaiting approval")
            payload = {key: value for key, value in stored.items() if key not in {"id", "state"}}
            payload.update({"approved": False, "denied_at": time.time()})
            if not self.database.transition_job(job_id, {"approval_required"}, "denied", payload): raise RuntimeError("sudo approval request changed before denial")
            return self.database.job(job_id) or {"id": job_id, "state": "denied"}
        if operation == "cancel":
            payload = {key: value for key, value in stored.items() if key not in {"id", "state"}}
            payload.update({"cancelled": True, **self._snapshot(job_id)})
            transitioned = self.database.transition_job(job_id, {"starting", "running"}, "cancelled", payload)
            if transitioned and process: self._kill_group(process)
            stored = self.database.job(job_id)
        elif operation == "resume":
            if stored["state"] == "running": return {"id": job_id, "state": "running", "resumed": False}
            if stored["state"] not in {"interrupted", "failed", "timed_out", "cancelled"}: raise ValueError(f"job in state {stored['state']!r} cannot be resumed")
            argv, cwd = stored.get("argv"), stored.get("cwd")
            if not isinstance(argv, list) or not isinstance(cwd, str): raise ValueError("job has no durable resume specification")
            return {
                **self._start_background(argv, Path(cwd), resumed_from=job_id, unrestricted=job_unrestricted),
                "resumed": True,
            }
        if operation == "logs":
            live = self._snapshot(job_id) if process and process.poll() is None else {}
            return self._format_output({"id": job_id, "state": stored["state"], "stdout": live.get("stdout", stored.get("stdout", "")), "stderr": live.get("stderr", stored.get("stderr", "")), "stdout_truncated": live.get("stdout_truncated", stored.get("stdout_truncated", False)), "stderr_truncated": live.get("stderr_truncated", stored.get("stderr_truncated", False))}, max_output_bytes=max_output_bytes, tail_lines=tail_lines, include_stdout=include_stdout, include_stderr=include_stderr)
        if operation == "result": return {"id": job_id, "state": stored["state"], "exit_code": stored.get("exit_code")}
        return self._format_output(stored or {"id": job_id, "state": "unknown"}, max_output_bytes=max_output_bytes, tail_lines=tail_lines, include_stdout=include_stdout, include_stderr=include_stderr)
