"""Per-user tunnel settings. Secrets use Windows DPAPI, never source/config text."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_char))]


def protect(data: bytes, decrypt: bool = False) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def validate(tunnel_id: str, key: str) -> None:
    if not re.fullmatch(r"tunnel_[a-f0-9]{32}", tunnel_id):
        raise ValueError("Tunnel ID must be tunnel_ followed by 32 hexadecimal characters.")
    if not re.fullmatch(r"sk-[A-Za-z0-9_-]{20,}", key):
        raise ValueError("Enter a valid OpenAI runtime API key with Tunnels Read/Use.")


class Tunnel:
    def __init__(self, app_data: Path):
        self.directory = app_data / "openai-tunnel"
        self.binary = app_data / "bin" / "tunnel-client.exe"
        self.settings = self.directory / "settings.json"
        self.secret = self.directory / "key.dpapi"
        self.health = self.directory / "health.url"
        self.process = None
        self.log = None
        self.retry_at = 0.0
        self.failures = 0
        self.error = ""

    def load(self):
        try:
            return json.loads(self.settings.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def save(self, tunnel_id: str, key: str, enabled: bool):
        tunnel_id, key = tunnel_id.strip(), key.strip()
        if not key:
            key = protect(self.secret.read_bytes(), decrypt=True).decode()
        validate(tunnel_id, key)
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.secret.with_suffix(".tmp")
        temporary.write_bytes(protect(key.encode()))
        os.replace(temporary, self.secret)
        temporary = self.settings.with_suffix(".tmp")
        temporary.write_text(json.dumps({"tunnel_id": tunnel_id, "enabled": bool(enabled)}), encoding="utf-8")
        os.replace(temporary, self.settings)
        self.stop()
        self.retry_at = 0
        self.failures = 0
        self.error = ""

    def start(self):
        config = self.load()
        if not config.get("enabled") or self.process is not None:
            return
        if not self.binary.is_file():
            raise FileNotFoundError("Install the official tunnel-client.exe in MyComp Bot/bin first.")
        key = protect(self.secret.read_bytes(), decrypt=True).decode()
        validate(config["tunnel_id"], key)
        self.health.unlink(missing_ok=True)
        environment = {**os.environ, "CONTROL_PLANE_API_KEY": key}
        # ponytail: one owned runtime; use channel-aware profiles if multiple MCP servers are needed.
        self.log = (self.directory / "runtime.log").open("w", encoding="utf-8")
        try:
            self.process = subprocess.Popen([str(self.binary), "run",
                "--control-plane.tunnel-id", config["tunnel_id"],
                "--control-plane.api-key", "env:CONTROL_PLANE_API_KEY",
                "--mcp.server-url", "http://127.0.0.1:8645/mcp",
                "--health.listen-addr", "127.0.0.1:0",
                "--health.url-file", str(self.health)],
                env=environment, stdout=self.log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            self.log.close()
            self.log = None
            raise

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            self.process = None
        if self.log:
            self.log.close()
            self.log = None

    def tick(self):
        if self.process is not None and self.process.poll() is not None:
            code = self.process.returncode
            self.stop()
            self.failures += 1
            self.retry_at = time.monotonic() + min(300, 5 * 2 ** min(self.failures, 6))
            self.error = f"Runtime exited ({code}); retry scheduled. See runtime.log."
        if self.process is None and time.monotonic() >= self.retry_at:
            try:
                self.start()
            except (OSError, ValueError, KeyError):
                self.error = "Cannot start tunnel. Check saved settings, key, and installed client."
                self.retry_at = time.monotonic() + 60

    def status(self):
        if self.process is None:
            return self.error or "Not connected"
        try:
            base = self.health.read_text(encoding="utf-8").strip()
            if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]+", base):
                return "Starting; waiting for private health URL"
            with urllib.request.urlopen(base + "/readyz", timeout=2) as response:
                return "Runtime ready; ChatGPT tool access still requires connector verification" if response.status == 200 else "Runtime not ready"
        except (OSError, ValueError):
            return "Runtime running; not ready. Check runtime.log for authentication or MCP errors."
