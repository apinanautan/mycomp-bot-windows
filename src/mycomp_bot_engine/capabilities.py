from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .database import Database

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}$")
_RUN_TIMEOUT_SECONDS = 30.0
_TERMINATE_GRACE_SECONDS = 1.0
_OUTPUT_LIMIT_BYTES = 64_000
_PIPE_CHUNK_BYTES = 8_192


def _process_group_exists(process_group_id: int) -> bool:
    if os.name == "nt":
        return True
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate every process in the isolated group and reap its leader."""
    if os.name == "nt":
        process.terminate()
        try:
            process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass

    deadline = time.monotonic() + _TERMINATE_GRACE_SECONDS
    while time.monotonic() < deadline and _process_group_exists(process.pid):
        time.sleep(0.01)

    # The leader may have exited while a descendant ignored SIGTERM. Address the
    # group by its original id so those descendants cannot outlive the run.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _read_bounded(stream: Any, output: bytearray, exceeded: threading.Event) -> None:
    try:
        while not exceeded.is_set():
            remaining = _OUTPUT_LIMIT_BYTES + 1 - len(output)
            if remaining <= 0:
                exceeded.set()
                break
            chunk = stream.read(min(_PIPE_CHUNK_BYTES, remaining))
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > _OUTPUT_LIMIT_BYTES:
                exceeded.set()
                break
    finally:
        stream.close()


class CapabilityRegistry:
    """Capability registry with immutable, tested active versions."""
    def __init__(self, directory: Path, database: Database, allowed_roots: tuple[Path, ...] = (), protected_paths: tuple[Path, ...] = ()) -> None:
        self.directory, self.database = directory.resolve(), database
        overlaps_allowed_root = any(self.directory == root.resolve() or self.directory.is_relative_to(root.resolve()) for root in allowed_roots)
        is_protected = any(self.directory == path.resolve() or self.directory.is_relative_to(path.resolve()) for path in protected_paths)
        if overlaps_allowed_root and not is_protected:
            raise ValueError("capability directory must not overlap remotely writable roots")
        self.directory.mkdir(parents=True, exist_ok=True); os.chmod(self.directory, 0o700)
        self._manage_lock = threading.RLock()

    def _source(self, name: str) -> tuple[bytes, str]:
        if not _NAME.fullmatch(name): raise KeyError("invalid capability name")
        path = self.directory / f"{name}.py"
        if not path.is_file() or path.is_symlink(): raise KeyError("capability not found")
        if os.name != "nt" and path.stat().st_uid != os.getuid(): raise KeyError("capability not found")
        source = path.read_bytes()
        if len(source) > 128_000: raise ValueError("capability exceeds source limit")
        return source, hashlib.sha256(source).hexdigest()

    @staticmethod
    def _validate(source: bytes) -> None:
        """Validation is syntactic only: no candidate source executes here."""
        tree = ast.parse(source)
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        if not {"execute", "self_test"} <= functions.keys():
            raise ValueError("capability must define execute(payload) and self_test()")
        execute = functions["execute"].args
        self_test = functions["self_test"].args
        if (
            len(execute.posonlyargs) + len(execute.args) != 1
            or execute.vararg is not None
            or execute.kwarg is not None
            or execute.kwonlyargs
            or execute.defaults
        ):
            raise ValueError("execute must have the signature execute(payload)")
        if (
            self_test.posonlyargs
            or self_test.args
            or self_test.vararg is not None
            or self_test.kwarg is not None
            or self_test.kwonlyargs
        ):
            raise ValueError("self_test must have the signature self_test()")

    @staticmethod
    def _validate_descriptor(descriptor: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(descriptor, dict):
            raise ValueError("descriptor must be an object")
        required = {"version", "description"}
        allowed = required | {
            "input_schema", "output_schema", "examples", "permissions",
            "side_effects", "supports_dry_run", "default_timeout_seconds",
            "execution_modes", "tags",
        }
        missing = required - set(descriptor)
        extra = set(descriptor) - allowed
        if missing or extra:
            raise ValueError(f"descriptor keys invalid; missing={sorted(missing)}, extra={sorted(extra)}")
        version, description = descriptor.get("version"), descriptor.get("description")
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){0,2}(?:[-+][A-Za-z0-9.-]+)?", version):
            raise ValueError("descriptor version must be a numeric version string")
        if not isinstance(description, str) or not description.strip() or len(description) > 500:
            raise ValueError("descriptor description must be 1 to 500 characters")
        result: dict[str, Any] = {"version": version, "description": description.strip()}
        for key in ("input_schema", "output_schema"):
            value = descriptor.get(key, {"type": "object"})
            if not isinstance(value, dict): raise ValueError(f"descriptor {key} must be an object")
            result[key] = value
        for key in ("examples", "permissions", "execution_modes", "tags"):
            defaults = {"examples": [], "permissions": [], "execution_modes": ["foreground", "background", "auto"], "tags": []}
            value = descriptor.get(key, defaults[key])
            if not isinstance(value, list) or not all(isinstance(item, (str, dict)) for item in value):
                raise ValueError(f"descriptor {key} must be a list")
            result[key] = value
        side_effects = descriptor.get("side_effects", "none")
        if not isinstance(side_effects, str) or len(side_effects) > 200:
            raise ValueError("descriptor side_effects must be a short string")
        result["side_effects"] = side_effects
        result["supports_dry_run"] = bool(descriptor.get("supports_dry_run", False))
        timeout = float(descriptor.get("default_timeout_seconds", _RUN_TIMEOUT_SECONDS))
        if timeout <= 0 or timeout > 3600:
            raise ValueError("descriptor default_timeout_seconds must be between 0 and 3600")
        result["default_timeout_seconds"] = timeout
        return result

    def _upsert(self, name: str, source_text: str | None, descriptor: dict[str, Any] | None) -> dict[str, Any]:
        """Test and atomically publish a candidate without disturbing the active version on failure."""
        if not _NAME.fullmatch(name):
            raise ValueError("invalid capability name")
        if not isinstance(source_text, str):
            raise ValueError("source must be a UTF-8 string")
        source = source_text.encode("utf-8")
        if not source or len(source) > 128_000:
            raise ValueError("capability source must be 1 to 128000 bytes")
        normalized_descriptor = self._validate_descriptor(descriptor)
        self._validate(source)
        try:
            passed = self._run(source, name, "test") is True
        except Exception as error:
            raise ValueError(f"capability self-test failed: {error}") from error
        if not passed:
            raise ValueError("capability self-test returned false")

        checksum = hashlib.sha256(source).hexdigest()
        destination = self.directory / f"{name}.py"
        with self._manage_lock:
            prior_source = destination.read_bytes() if destination.is_file() and not destination.is_symlink() else None
            with self.database.transaction():
                prior_active = self.database.connection.execute(
                    "SELECT checksum FROM capabilities WHERE name = ? AND state = 'active'", (name,)
                ).fetchone()
            staged_fd, staged_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".stage", dir=self.directory)
            staged = Path(staged_name)
            try:
                with os.fdopen(staged_fd, "wb") as handle:
                    if os.name != "nt":
                        os.fchmod(handle.fileno(), 0o600)
                    handle.write(source)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(staged, destination)
                if os.name != "nt":
                    directory_fd = os.open(self.directory, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)

                try:
                    with self.database.transaction():
                        self.database.connection.execute(
                            "INSERT OR REPLACE INTO capability_versions(name, checksum, source, tested, test_error, created) VALUES (?, ?, ?, 1, NULL, ?)",
                            (name, checksum, source, time.time()),
                        )
                        self.database.connection.execute(
                            "INSERT OR REPLACE INTO capability_metadata(name, checksum, version, description, metadata_json) VALUES (?, ?, ?, ?, ?)",
                            (name, checksum, normalized_descriptor["version"], normalized_descriptor["description"], json.dumps(normalized_descriptor, sort_keys=True)),
                        )
                        self.database.connection.execute(
                            "INSERT OR REPLACE INTO capabilities VALUES (?, 'active', ?)", (name, checksum)
                        )
                        self.database.connection.execute(
                            "INSERT INTO capability_history(name, checksum, state, created) VALUES (?, ?, 'active', ?)",
                            (name, checksum, time.time()),
                        )
                        self.database.connection.commit()
                except BaseException:
                    self.database.connection.rollback()
                    restore_fd, restore_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".restore", dir=self.directory)
                    restore = Path(restore_name)
                    try:
                        if prior_source is None:
                            os.close(restore_fd)
                            restore.unlink(missing_ok=True)
                            destination.unlink(missing_ok=True)
                        else:
                            with os.fdopen(restore_fd, "wb") as handle:
                                if os.name != "nt":
                                    os.fchmod(handle.fileno(), 0o600)
                                handle.write(prior_source)
                                handle.flush()
                                os.fsync(handle.fileno())
                            os.replace(restore, destination)
                    finally:
                        restore.unlink(missing_ok=True)
                    raise
            finally:
                staged.unlink(missing_ok=True)

        return {
            "name": name,
            "state": "active",
            "change": "updated" if prior_active else "installed",
            "checksum": checksum,
            "descriptor": normalized_descriptor,
        }

    @staticmethod
    def _run(source: bytes, name: str, action: str, payload: dict[str, Any] | None = None, *, timeout_seconds: float | None = None, process_callback: Any = None) -> Any:
        # Candidate code runs only in a short-lived isolated subprocess. This is a
        # trust boundary for locally installed code, not a sandbox for hostile code.
        runner = """import json,sys\ns={};exec(compile(open(sys.argv[1],'rb').read(),sys.argv[1],'exec'),s)\na=sys.argv[2]\nr=s['self_test']() if a=='test' else s['execute'](json.loads(sys.stdin.read()))\nprint(json.dumps(r))\n"""
        with tempfile.TemporaryDirectory(prefix="mycomp-cap-") as temp:
            path = Path(temp) / f"{name}.py"; path.write_bytes(source); os.chmod(path, 0o600)
            environment = {"PATH": os.getenv("PATH", ""), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(Path.home())}
            if os.name == "nt":
                environment["USERPROFILE"] = str(Path.home())
            process = subprocess.Popen([sys.executable, "-B", "-I", "-c", runner, str(path), action], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=temp, env=environment, start_new_session=os.name != "nt", creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0)
            if process_callback is not None: process_callback(process)
            stdout = bytearray()
            stderr = bytearray()
            exceeded = threading.Event()
            readers = [
                threading.Thread(target=_read_bounded, args=(process.stdout, stdout, exceeded), daemon=True),
                threading.Thread(target=_read_bounded, args=(process.stderr, stderr, exceeded), daemon=True),
            ]
            for reader in readers:
                reader.start()
            cleanup_done = False
            try:
                assert process.stdin is not None
                try:
                    process.stdin.write(json.dumps(payload or {}).encode())
                    process.stdin.close()
                except BrokenPipeError:
                    pass

                deadline = time.monotonic() + (_RUN_TIMEOUT_SECONDS if timeout_seconds is None else float(timeout_seconds))
                while process.poll() is None and not exceeded.is_set():
                    if time.monotonic() >= deadline:
                        cleanup_done = True
                        _stop_process_group(process)
                        raise ValueError("capability timed out")
                    time.sleep(0.01)

                if exceeded.is_set():
                    cleanup_done = True
                    _stop_process_group(process)
                else:
                    process.wait()
                    # A capability must not leave background descendants behind.
                    if os.name != "nt":
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            pass
            except BaseException:
                if not cleanup_done:
                    _stop_process_group(process)
                raise
            finally:
                for reader in readers:
                    reader.join(timeout=2)

        if exceeded.is_set():
            raise ValueError("capability output exceeds limit")
        if process.returncode:
            message = bytes(stderr).decode(errors="replace") or "capability failed"
            raise ValueError(message[-1000:])
        return json.loads(bytes(stdout))

    def search(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.py") if _NAME.fullmatch(p.stem) and not p.is_symlink())

    def search_metadata(self) -> list[dict[str, Any]]:
        """Return durable self-describing discovery data for active capabilities."""
        with self.database.transaction():
            rows = self.database.connection.execute(
                """SELECT c.name, c.state, c.checksum, m.version, m.description, m.metadata_json
                   FROM capabilities AS c
                   LEFT JOIN capability_metadata AS m
                     ON m.name = c.name AND m.checksum = c.checksum
                   ORDER BY c.name"""
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            metadata: dict[str, Any] = {}
            try:
                value = json.loads(row[5] or "{}")
                if isinstance(value, dict): metadata = value
            except (TypeError, json.JSONDecodeError):
                pass
            results.append({
                "name": row[0], "state": row[1], "checksum": row[2],
                "version": row[3], "description": row[4], **{
                    key: value for key, value in metadata.items()
                    if key not in {"version", "description"}
                },
            })
        return results

    def _descriptor_for(self, name: str, checksum: str) -> dict[str, Any]:
        with self.database.transaction():
            row = self.database.connection.execute(
                "SELECT metadata_json, version, description FROM capability_metadata WHERE name = ? AND checksum = ?",
                (name, checksum),
            ).fetchone()
        if not row:
            return {"version": "0", "description": name, "default_timeout_seconds": _RUN_TIMEOUT_SECONDS}
        try:
            value = json.loads(row[0] or "{}")
            if isinstance(value, dict): return {"version": row[1], "description": row[2], **value}
        except (TypeError, json.JSONDecodeError):
            pass
        return {"version": row[1], "description": row[2], "default_timeout_seconds": _RUN_TIMEOUT_SECONDS}

    def _store(self, name: str, checksum: str, source: bytes, tested: bool, error: str | None = None) -> None:
        with self.database.transaction():
            self.database.connection.execute("INSERT OR REPLACE INTO capability_versions(name, checksum, source, tested, test_error, created) VALUES (?, ?, ?, ?, ?, ?)", (name, checksum, source, int(tested), error, time.time()))
            self.database.connection.commit()

    def manage(self, operation: str, name: str, source: str | None = None, descriptor: dict[str, Any] | None = None) -> dict[str, Any]:
        if operation == "upsert":
            return self._upsert(name, source, descriptor)
        if operation in {"validate", "test", "activate"}:
            source, checksum = self._source(name); self._validate(source)
            if operation == "validate": self._store(name, checksum, source, False); return {"name": name, "valid": True}
            if operation == "test":
                try: passed = self._run(source, name, "test") is True
                except Exception as error: self._store(name, checksum, source, False, str(error)); return {"name": name, "valid": True, "test": False, "error": str(error)}
                self._store(name, checksum, source, passed, None if passed else "self_test returned false"); return {"name": name, "valid": True, "test": passed}
            with self.database.transaction():
                row = self.database.connection.execute("SELECT tested FROM capability_versions WHERE name = ? AND checksum = ?", (name, checksum)).fetchone()
                if not row or not row[0]: raise PermissionError("capability must pass test before activation")
                self.database.connection.execute("INSERT OR REPLACE INTO capabilities VALUES (?, 'active', ?)", (name, checksum)); self.database.connection.execute("INSERT INTO capability_history(name, checksum, state, created) VALUES (?, ?, 'active', ?)", (name, checksum, time.time())); self.database.connection.commit()
            return {"name": name, "state": "active"}
        with self.database.transaction():
            if operation == "deactivate":
                row = self.database.connection.execute("SELECT checksum FROM capabilities WHERE name = ?", (name,)).fetchone()
                if not row: raise KeyError("capability is not registered")
                self.database.connection.execute("UPDATE capabilities SET state = 'inactive' WHERE name = ?", (name,)); self.database.connection.execute("INSERT INTO capability_history(name, checksum, state, created) VALUES (?, ?, 'inactive', ?)", (name, row[0], time.time())); self.database.connection.commit(); return {"name": name, "state": "inactive"}
            if operation == "rollback":
                row = self.database.connection.execute("SELECT checksum FROM capability_history WHERE name = ? AND state = 'active' ORDER BY id DESC LIMIT 1 OFFSET 1", (name,)).fetchone()
                if not row: raise ValueError("no prior active capability version")
                version = self.database.connection.execute("SELECT tested FROM capability_versions WHERE name = ? AND checksum = ?", (name, row[0])).fetchone()
                if not version or not version[0]: raise PermissionError("prior capability version is not tested")
                self.database.connection.execute("INSERT OR REPLACE INTO capabilities VALUES (?, 'active', ?)", (name, row[0])); self.database.connection.execute("INSERT INTO capability_history(name, checksum, state, created) VALUES (?, ?, 'active', ?)", (name, row[0], time.time())); self.database.connection.commit(); return {"name": name, "state": "active", "checksum": row[0]}
        raise ValueError("unsupported capability operation")

    def _active_version(self, name: str) -> tuple[bytes, str, dict[str, Any]]:
        with self.database.transaction():
            row = self.database.connection.execute("SELECT state, checksum FROM capabilities WHERE name = ?", (name,)).fetchone()
            if not row or row[0] != "active": raise PermissionError("capability is not active")
            version = self.database.connection.execute("SELECT source, tested FROM capability_versions WHERE name = ? AND checksum = ?", (name, row[1])).fetchone()
        if not version or not version[1]: raise PermissionError("active capability version is unavailable")
        self._validate(version[0])
        return version[0], row[1], self._descriptor_for(name, row[1])

    def _start_job(self, name: str, payload: dict[str, Any], source: bytes, descriptor: dict[str, Any], resumed_from: str | None = None) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        timeout = float(payload.pop("__timeout_seconds", descriptor.get("default_timeout_seconds", _RUN_TIMEOUT_SECONDS)))
        record = {"kind": "capability", "capability": name, "payload": payload, "timeout_seconds": timeout, "started": time.time(), "resumed_from": resumed_from}
        self.database.save_job(job_id, "running", record)
        if not hasattr(self, "_job_processes"):
            self._job_processes, self._job_threads, self._job_lock = {}, {}, threading.RLock()

        def remember(process: subprocess.Popen[bytes]) -> None:
            with self._job_lock: self._job_processes[job_id] = process

        def worker() -> None:
            try:
                result = self._run(source, name, "execute", payload, timeout_seconds=timeout, process_callback=remember)
                state, extra = "finished", {"result": result, "finished": time.time()}
            except Exception as error:
                state, extra = "failed", {"error": str(error), "finished": time.time()}
            finally:
                with self._job_lock:
                    self._job_processes.pop(job_id, None)
                    self._job_threads.pop(job_id, None)
            latest = self.database.job(job_id) or record
            if latest.get("state") == "cancelled": return
            merged = {key: value for key, value in latest.items() if key not in {"id", "state"}}
            merged.update(extra)
            self.database.transition_job(job_id, {"running"}, state, merged)

        thread = threading.Thread(target=worker, daemon=True, name=f"capability-{name}-{job_id[:8]}")
        with self._job_lock: self._job_threads[job_id] = thread
        thread.start()
        return {"job_id": job_id, "state": "running", "kind": "capability", "capability": name}

    def execute(self, name: str, payload: dict[str, Any]) -> Any:
        if not isinstance(payload, dict): raise ValueError("payload must be an object")
        payload = dict(payload)
        execution = payload.pop("__execution", {})
        if execution is None: execution = {}
        if not isinstance(execution, dict): raise ValueError("__execution must be an object")
        mode = str(execution.get("mode", "foreground"))
        source, _, descriptor = self._active_version(name)
        supported = descriptor.get("execution_modes", ["foreground", "background", "auto"])
        if mode not in supported: raise ValueError(f"execution mode {mode!r} is not supported")
        if "timeout_seconds" in execution: payload["__timeout_seconds"] = execution["timeout_seconds"]
        if mode in {"background", "auto"}:
            launched = self._start_job(name, payload, source, descriptor)
            if mode == "background": return launched
            timeout = min(max(float(execution.get("wait_seconds", 5)), 0), 60)
            return self.control("wait", launched["job_id"], timeout_seconds=timeout)
        timeout = float(payload.pop("__timeout_seconds", descriptor.get("default_timeout_seconds", _RUN_TIMEOUT_SECONDS)))
        return self._run(source, name, "execute", payload, timeout_seconds=timeout)

    def has_job(self, job_id: str) -> bool:
        stored = self.database.job(job_id)
        return bool(stored and stored.get("kind") == "capability")

    def control(self, operation: str, job_id: str, *, timeout_seconds: float | None = None, **_: Any) -> dict[str, Any]:
        stored = self.database.job(job_id)
        if not stored or stored.get("kind") != "capability": raise KeyError("capability job not found")
        if not hasattr(self, "_job_processes"):
            self._job_processes, self._job_threads, self._job_lock = {}, {}, threading.RLock()
        if operation == "wait":
            with self._job_lock: thread = self._job_threads.get(job_id)
            if thread: thread.join(timeout=min(max(float(timeout_seconds or 20), 0), 60))
            return self.database.job(job_id) or stored
        if operation == "cancel":
            with self._job_lock: process = self._job_processes.get(job_id)
            if process is not None: _stop_process_group(process)
            payload = {key: value for key, value in stored.items() if key not in {"id", "state"}}
            payload.update({"cancelled": True, "cancelled_at": time.time()})
            self.database.transition_job(job_id, {"running"}, "cancelled", payload)
            return self.database.job(job_id) or stored
        if operation == "resume":
            if stored["state"] not in {"failed", "cancelled", "interrupted", "timed_out"}:
                raise ValueError(f"job in state {stored['state']!r} cannot be resumed")
            source, _, descriptor = self._active_version(str(stored["capability"]))
            return {**self._start_job(str(stored["capability"]), dict(stored.get("payload") or {}), source, descriptor, resumed_from=job_id), "resumed": True}
        if operation == "logs":
            return {"id": job_id, "state": stored["state"], "kind": "capability", "capability": stored.get("capability"), "error": stored.get("error")}
        if operation == "result":
            return {"id": job_id, "state": stored["state"], "result": stored.get("result"), "error": stored.get("error")}
        if operation == "status": return stored
        raise ValueError("unsupported capability job operation")
