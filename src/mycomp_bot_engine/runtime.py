from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .capabilities import CapabilityRegistry


class RuntimeController:
    """Durable control-plane state shared with the native app supervisor."""

    def __init__(self, data_dir: Path, capabilities: CapabilityRegistry) -> None:
        self.directory = data_dir / "runtime"
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self.log_path = self.directory / "engine.log"
        self.restart_request_path = self.directory / "restart-request.json"
        self.generation_path = self.directory / "generation.json"
        self.ui_pending_dir = self.directory / "ui-folder-pending"
        self.ui_decision_dir = self.directory / "ui-folder-decisions"
        self.ui_policy_path = data_dir / "folder-popup-policy.json"
        self.ui_pending_dir.mkdir(parents=True, exist_ok=True)
        self.ui_decision_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.ui_pending_dir, 0o700)
        os.chmod(self.ui_decision_dir, 0o700)
        self.capabilities = capabilities
        self.started_at = time.time()
        self._lock = threading.RLock()
        self._generation = self._read_generation()
        self._record("engine_started", generation=self._generation)

    def _read_generation(self) -> int:
        try:
            value = json.loads(self.generation_path.read_text(encoding="utf-8"))
            return max(0, int(value.get("generation", 0)))
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _record(self, event: str, **details: Any) -> None:
        entry = {"at": time.time(), "event": event, "pid": os.getpid(), **details}
        encoded = json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock:
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(encoded)
            os.chmod(self.log_path, 0o600)

    def _capability_snapshot(self) -> dict[str, Any]:
        available = self.capabilities.search()
        sources: list[tuple[str, str]] = []
        for name in available:
            try:
                _, checksum = self.capabilities._source(name)
            except (KeyError, OSError, ValueError):
                continue
            sources.append((name, checksum))
        with self.capabilities.database.transaction():
            active = [
                {"name": row[0], "checksum": row[1]}
                for row in self.capabilities.database.connection.execute(
                    "SELECT name, checksum FROM capabilities WHERE state = 'active' ORDER BY name"
                ).fetchall()
            ]
        fingerprint = hashlib.sha256(
            json.dumps({"sources": sources, "active": active}, sort_keys=True).encode()
        ).hexdigest()
        return {"available": [name for name, _ in sources], "active": active, "fingerprint": fingerprint}

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "mycomp-bot",
            "pid": os.getpid(),
            "started_at": self.started_at,
            "generation": self._generation,
            "restart_pending": self.restart_request_path.exists(),
        }

    def diagnostics(self) -> dict[str, Any]:
        return {
            **self.health(),
            "runtime_dir": str(self.directory),
            "log_path": str(self.log_path),
            "restart_request_path": str(self.restart_request_path),
            "capabilities": self._capability_snapshot(),
            "ui_folder_approvals": self.ui_control("ui_pending"),
            "ui_folder_policy": self.ui_control("ui_policy"),
        }

    def _ui_pending(self) -> list[dict[str, Any]]:
        requests: list[dict[str, Any]] = []
        for path in sorted(self.ui_pending_dir.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                requests.append(value)
        return requests

    def _ui_policy(self) -> dict[str, Any]:
        try:
            value = json.loads(self.ui_policy_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {"version": 1, "rules": []}
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {"version": 1, "rules": []}

    def _ui_write_decision(self, request_id: str, decision: str) -> dict[str, Any]:
        request_path = self.ui_pending_dir / f"{request_id}.json"
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise KeyError("UI approval request not found") from error
        if not isinstance(request, dict) or request.get("id") != request_id:
            raise ValueError("invalid UI approval request")
        if decision in {"allow_always", "deny_always"}:
            policy = self._ui_policy()
            rules = policy.get("rules") if isinstance(policy.get("rules"), list) else []
            app_id = str(request.get("app_id", ""))
            app_name = str(request.get("app_name", ""))
            folder = str(request.get("folder", ""))
            rules = [rule for rule in rules if not (
                isinstance(rule, dict)
                and str(rule.get("folder", "")) == folder
                and ((app_id and str(rule.get("app_id", "")) == app_id) or (app_name and str(rule.get("app_name", "")) == app_name))
            )]
            rules.append({"app_id": app_id, "app_name": app_name, "folder": folder, "decision": decision})
            policy = {"version": 1, "rules": rules}
            self._atomic_json(self.ui_policy_path, policy)
        result = {"id": request_id, "decision": decision, "decided_at": time.time()}
        self._atomic_json(self.ui_decision_dir / f"{request_id}.json", result)
        self._record("ui_folder_decision", request_id=request_id, decision=decision)
        return {"state": "decision_recorded", **result, "request": request}

    def ui_control(self, operation: str) -> dict[str, Any]:
        if operation == "ui_pending":
            requests = self._ui_pending()
            return {"requests": requests, "count": len(requests)}
        if operation == "ui_policy":
            return self._ui_policy()
        actions = {
            "ui_allow_once:": "allow_once",
            "ui_allow_always:": "allow_always",
            "ui_deny:": "deny",
            "ui_deny_always:": "deny_always",
        }
        for prefix, decision in actions.items():
            if operation.startswith(prefix):
                request_id = operation[len(prefix):].strip()
                if not request_id or any(character not in "0123456789abcdef" for character in request_id.lower()):
                    raise ValueError("invalid UI approval request id")
                return self._ui_write_decision(request_id, decision)
        raise ValueError("unsupported UI control operation")

    def ui_job_control(self, operation: str, request_id: str) -> dict[str, Any]:
        request_path = self.ui_pending_dir / f"{request_id}.json"
        decision_path = self.ui_decision_dir / f"{request_id}.json"
        if operation == "status":
            if request_path.exists():
                request = json.loads(request_path.read_text(encoding="utf-8"))
                decision = None
                if decision_path.exists():
                    decision = json.loads(decision_path.read_text(encoding="utf-8")).get("decision")
                return {"id": request_id, "state": "decision_recorded" if decision else "approval_required", "approval_kind": "folder_permission", "decision": decision, **request}
            raise KeyError("UI approval request not found")
        mapping = {
            "approve": "allow_once",
            "approve_always": "allow_always",
            "deny": "deny",
            "deny_always": "deny_always",
        }
        if operation not in mapping:
            raise ValueError("unsupported UI approval operation")
        return self._ui_write_decision(request_id, mapping[operation])

    def has_ui_request(self, request_id: str) -> bool:
        return (self.ui_pending_dir / f"{request_id}.json").exists()

    def logs(self, limit: int = 100) -> dict[str, Any]:
        limit = min(max(limit, 1), 1_000)
        try:
            with self.log_path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                start = max(0, size - 1_000_000)
                stream.seek(start)
                if start:
                    stream.readline()  # discard a partial JSON line
                lines = stream.read().decode("utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            lines, start = [], 0
        entries: list[Any] = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                entries.append({"event": "unparsed_log", "message": line})
        return {"entries": entries, "log_path": str(self.log_path), "truncated": bool(start or len(lines) > limit)}

    def reload(self) -> dict[str, Any]:
        with self._lock:
            previous = self._read_generation_state()
            snapshot = self._capability_snapshot()
            self._generation += 1
            state = {"generation": self._generation, "reloaded_at": time.time(), **snapshot}
            self._atomic_json(self.generation_path, state)
            changed = previous.get("fingerprint") != snapshot["fingerprint"]
            self._record("capabilities_reloaded", generation=self._generation, changed=changed)
        return {"state": "reloaded", "changed": changed, **state}

    def _read_generation_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.generation_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    def request_restart(self) -> dict[str, Any]:
        request = {
            "id": uuid.uuid4().hex,
            "requested_at": time.time(),
            "requesting_pid": os.getpid(),
            "status": "pending",
        }
        with self._lock:
            self._atomic_json(self.restart_request_path, request)
            self._record("restart_requested", request_id=request["id"])
        return {"state": "restart_requested", "request_file": str(self.restart_request_path), **request}

    def shutdown(self) -> None:
        self._record("engine_stopped", uptime_seconds=max(0.0, time.time() - self.started_at))
