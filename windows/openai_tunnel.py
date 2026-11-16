"""Per-user tunnel settings. Secrets use Windows DPAPI, never source/config text."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import time
import urllib.request
from urllib.parse import urlsplit


LOCAL_MCP_ENDPOINT = "http://127.0.0.1:8645/mcp"


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


def validate_tunnel_id(tunnel_id: str) -> str:
    if not isinstance(tunnel_id, str) or not re.fullmatch(r"tunnel_[a-f0-9]{32}", tunnel_id):
        raise ValueError("Save a valid Tunnel ID first (tunnel_ and 32 hexadecimal characters).")
    return tunnel_id


def validate(tunnel_id: str, key: str) -> None:
    validate_tunnel_id(tunnel_id)
    if not re.fullmatch(r"sk-[A-Za-z0-9_-]{20,}", key):
        raise ValueError("Enter a valid OpenAI runtime API key with Tunnels Read/Use.")


class Tunnel:
    def __init__(self, app_data: Path):
        self.directory = app_data / "openai-tunnel"
        self.binary = app_data / "bin" / "tunnel-client.exe"
        self.settings = self.directory / "settings.json"
        self.secret = self.directory / "key.dpapi"
        self.health = self.directory / "health.url"
        # Legacy settings/key are never moved or overwritten when registering
        # an additional account's Tunnel. Active profile selection is explicit.
        self.legacy_settings = self.settings
        self.legacy_secret = self.secret
        self.legacy_health = self.health
        self.profiles_dir = self.directory / "profiles"
        self.active_profile_file = self.profiles_dir / "active.json"
        self.active_profile_name = None
        try:
            active = json.loads(self.active_profile_file.read_text(encoding="utf-8"))
            selected = active.get("name") if isinstance(active, dict) else None
            if selected and self._valid_profile_name(selected):
                info = self._profile_paths(selected)
                if info[0].is_file():
                    self.active_profile_name = selected
                    self.settings, self.secret, self.health = info
        except (OSError, ValueError, TypeError):
            pass
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

    @staticmethod
    def _valid_profile_name(name: str) -> bool:
        return isinstance(name, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,47}", name) is not None

    def _profile_paths(self, name: str) -> tuple[Path, Path, Path]:
        if not self._valid_profile_name(name):
            raise ValueError("Profile name: use 1–48 ASCII letters, digits, _ or -.")
        return (
            self.profiles_dir / f"{name}.json",
            self.profiles_dir / f"{name}.dpapi",
            self.profiles_dir / f"{name}.health.url",
        )

    @staticmethod
    def _atomic_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_suffix(path.suffix + ".tmp")
        try:
            staging.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(staging, path)
        finally:
            staging.unlink(missing_ok=True)

    def list_profiles(self) -> list[str]:
        """Return saved profile labels, not secrets or identities inferred from PIDs."""
        if not self.profiles_dir.is_dir():
            return []
        result = []
        for file in self.profiles_dir.glob("*.json"):
            if file.name == "active.json" or not self._valid_profile_name(file.stem):
                continue
            try:
                doc = json.loads(file.read_text(encoding="utf-8"))
                if isinstance(doc, dict) and doc.get("name") == file.stem:
                    validate_tunnel_id(doc.get("tunnel_id", ""))
                    result.append(file.stem)
            except (OSError, ValueError, TypeError):
                continue
        return sorted(result, key=str.casefold)

    def profile_info(self, name: str) -> dict:
        metadata, secret, _ = self._profile_paths(name)
        data = json.loads(metadata.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("name") != name:
            raise ValueError("Invalid named Tunnel profile.")
        validate_tunnel_id(data.get("tunnel_id", ""))
        return {
            "name": name,
            "tunnel_id": data["tunnel_id"],
            "organization": data.get("organization", ""),
            "workspace": data.get("workspace", ""),
            "has_api_key": secret.is_file(),
            "active": self.active_profile_name == name,
        }

    def save_profile(self, name: str, tunnel_id: str, key: str = "",
                     organization: str = "", workspace: str = "") -> dict:
        """Persist new Tunnel ID immediately; encrypt any new key separately.

        This NEVER changes the legacy active Tunnel. Activation is separate.
        """
        tunnel_id = validate_tunnel_id(tunnel_id.strip())
        metadata, secret, _ = self._profile_paths(name)
        for hint in (organization, workspace):
            if not isinstance(hint, str) or len(hint) > 200 or any(ord(c) < 32 for c in hint):
                raise ValueError("Invalid organization/workspace label.")
        if metadata.exists():
            old = self.profile_info(name)
            if old["tunnel_id"] != tunnel_id:
                raise ValueError("Profile already contains another Tunnel ID; use a new profile name.")
            # Adding a key later must not erase the organization/workspace
            # metadata already recorded with this Tunnel ID.
            if not organization:
                organization = old["organization"]
            if not workspace:
                workspace = old["workspace"]
        if key.strip():
            validate(tunnel_id, key.strip())
            protected = protect(key.strip().encode("utf-8"))
            secret.parent.mkdir(parents=True, exist_ok=True)
            staging = secret.with_suffix(".dpapi.tmp")
            try:
                staging.write_bytes(protected)
                os.replace(staging, secret)
            finally:
                staging.unlink(missing_ok=True)
        self._atomic_json(metadata, {
            "name": name, "tunnel_id": tunnel_id,
            "organization": organization, "workspace": workspace,
            "enabled": self.active_profile_name == name and bool(self.load().get("enabled")),
        })
        return self.profile_info(name)

    def activate_profile(self, name: str) -> None:
        """Explicit activation only, after an encrypted credential exists."""
        metadata, secret, health = self._profile_paths(name)
        info = self.profile_info(name)
        if not info["has_api_key"]:
            raise ValueError("Save a new runtime API key for this profile first.")
        key = protect(secret.read_bytes(), decrypt=True).decode("utf-8")
        validate(info["tunnel_id"], key)
        if not self.binary.is_file():
            raise FileNotFoundError("Install the official tunnel-client.exe first.")
        self.stop()
        active_settings = json.loads(metadata.read_text(encoding="utf-8"))
        active_settings["enabled"] = True
        self._atomic_json(metadata, active_settings)
        self._atomic_json(self.active_profile_file, {"name": name})
        self.active_profile_name = name
        self.settings, self.secret, self.health = metadata, secret, health
        self.retry_at = 0
        self.failures = 0
        self.error = ""
        self.start()

    @property
    def mcp_endpoint(self) -> str:
        """The exact local binding passed to the Tunnel runtime."""
        return LOCAL_MCP_ENDPOINT

    def plugin_prompt(self, plugin_name: str, tailscale_base: str, *, computer_name: str | None = None) -> str:
        """Generate a fresh-account setup prompt; never expose existing tunnel IDs or keys.

        Existing settings are intentionally NOT included: the recipient GPT may
        be signed into a different Platform organization or ChatGPT account.
        """
        name = plugin_name.strip() if isinstance(plugin_name, str) else ""
        if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
            raise ValueError("Enter a plugin name (1–80 characters) before creating a prompt.")
        machine = socket.gethostname() if computer_name is None else computer_name
        if not isinstance(machine, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", machine):
            raise ValueError("Invalid local Windows computer name.")

        return f"""# {name} — ติดตั้งสกิลให้ทำงานเก่งและเร็ว

เครื่อง Windows: {machine}
ที่มาของสกิล: https://github.com/apinanautan/mycomp-bot-windows (โฟลเดอร์ skills/)

**ภารกิจ:** ติดตั้ง/อัปเดตสกิลของ {name} เท่านั้น ไม่ต้องตั้งค่า Tailscale, Tunnel, OAuth หรือ Remote Desktop และไม่ต้องสร้างหรือเปลี่ยนชื่อปลั๊กอิน ใช้การเชื่อมต่อที่ใช้งานอยู่ตอนนี้ได้เลย

1. ติดตั้งให้ครบ 5 ชุดสกิลจาก skills/ ในโปรเจกต์ (ถ้ามีอยู่แล้วและเนื้อหาตรงกันให้ข้าม ถ้าเก่ากว่าให้อัปเดต):
   - fast-batch — วางแผนก่อน แล้วรวมหลายขั้นตอนในคำสั่งเดียว (batch_read, batch_execute, steps) เพื่อความเร็ว
   - mycomp-operator — เลือกเครื่องและช่องทางให้ถูก ไม่ยุ่งแอปอื่น และรายงานตามหลักฐานจริง (รวม PLAYBOOK.md)
   - development-loop — ใช้ตอนแก้โค้ด: ตรวจก่อน แก้น้อยที่สุด ทดสอบ แล้วรายงานตรงตามจริง
   - tidmunz-studio-ai-operator — ชุดสกิลควบคุม Tidmunz Studio ทั้งหมด (อ่าน catalog.json แล้วติดตั้งทุกสกิลในโฟลเดอร์ เช่น tidmunz-control, tidmunz-device-routing, tidmunz-auto-workflow, tidmunz-finish-job) ใช้ทุกครั้งที่ผู้ใช้สั่งงาน Tidmunz Studio
   - codex-luna — ส่งงานหลายขั้นตอน หรือแบ่งงานให้ Codex CLI (gpt-6-luna) ทำพร้อมกันได้สูงสุด 3 งาน เพื่อใช้โควต้า Codex ให้คุ้ม ตอนติดตั้ง/ทดสอบให้รัน codex login status ถ้ายังไม่ล็อกอินให้เปิดหน้าต่างล็อกอิน (Start-Process codex -ArgumentList 'login') แล้วรอผู้ใช้ล็อกอิน ถ้าล็อกอินแล้วไม่ต้องเปิด จากนั้นเช็กว่าอีเมลที่ Codex ล็อกอินตรงกับอีเมลของบัญชี ChatGPT นี้ (ถามผู้ใช้ครั้งเดียวแล้วจำไว้) ถ้าไม่ตรงห้ามใช้ Luna และให้ล็อกอินใหม่ด้วยบัญชีที่ถูก
2. ลบสกิลเก่าที่เลิกใช้แล้วถ้ามี: operator-clarity, tool-routing, connection-recovery, ponytail, agent-desktop-portable ไม่ต้องติดตั้ง agent-desktop แยก (ใช้ tidmunz-agent-desktop ในชุด Tidmunz แทน)
3. ทดสอบสั้นๆ ด้วย batch_execute ครั้งเดียว เช่น {{"kind":"filesystem","operation":"list","path":"."}} และ {{"kind":"dom_cdp","action":"status"}} เพื่อยืนยันว่าเครื่องมือตอบได้
4. สรุปสั้นๆ ว่าสกิลไหนติดตั้ง/อัปเดต/ข้าม/ลบ
5. **อัปเดตสกิล Tidmunz อัตโนมัติ (จำไว้เป็นกฎถาวร):** ทุกครั้งก่อนเริ่มงาน Tidmunz Studio ให้อ่าน https://github.com/tidmunzsocial-lab/tidmunz-studio/blob/main/plugins/tidmunz-studio-ai-operator/skills/catalog.json (branch main) เทียบ version กับที่ติดตั้งอยู่ ถ้ามีสกิลใหม่หรือเนื้อหาเปลี่ยน ให้อ่าน SKILL.md ล่าสุดแล้วอัปเดต/ติดตั้งเองทันทีโดยไม่ต้องถามผู้ใช้ จากนั้นทำงานต่อด้วยคำสั่งล่าสุด ถ้าอ่าน GitHub ไม่ได้ให้ใช้สกิลที่มีอยู่และบอกผู้ใช้สั้นๆ

กฎ: ทำงาน Tidmunz Studio ได้เมื่อผู้ใช้สั่ง โดยทำตามสกิล tidmunz-* ห้ามแตะ Orchestrator หรือแอปอื่นที่ไม่เกี่ยว ห้ามเปิดลิงก์บนหน้าต่าง ChatGPT ที่ผู้ใช้อ่านอยู่ ห้ามแสดง API key, token หรือ secret"""

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
        extra = {}
        if self.active_profile_name:
            extra = {k: v for k, v in self.load().items() if k in ("name", "organization", "workspace")}
        temporary.write_text(json.dumps({**extra, "tunnel_id": tunnel_id, "enabled": bool(enabled)}), encoding="utf-8")
        os.replace(temporary, self.settings)
        self.stop()
        self.retry_at = 0
        self.failures = 0
        self.error = ""

    def _configured_oauth_origin(self) -> str | None:
        """Trust only the HTTPS OAuth origin the user configured for this MyComp Bot."""
        public_url = os.environ.get("MYCOMP_PUBLIC_BASE_URL", "").strip()
        if not public_url:
            try:
                for line in (self.directory.parent / ".env").read_text(encoding="utf-8-sig").splitlines():
                    if line.strip().startswith("MYCOMP_PUBLIC_BASE_URL="):
                        public_url = line.split("=", 1)[1].strip().strip(chr(34) + chr(39))
                        break
            except OSError:
                return None
        try:
            parsed = urlsplit(public_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                return None
            if parsed.hostname.endswith(".invalid") or parsed.hostname == "localhost":
                return None
            if not parsed.port or parsed.port == 443:
                return f"https://{parsed.hostname.lower()}"
            return f"https://{parsed.hostname.lower()}:{parsed.port}"
        except ValueError:
            return None

    def start(self):
        config = self.load()
        if not config.get("enabled") or self.process is not None:
            return
        if not self.binary.is_file():
            raise FileNotFoundError("Install the official tunnel-client.exe in MyComp Bot/bin first.")
        key = protect(self.secret.read_bytes(), decrypt=True).decode()
        validate(config["tunnel_id"], key)
        self.health.unlink(missing_ok=True)
        self._stop_stale_clients()
        environment = {**os.environ, "CONTROL_PLANE_API_KEY": key}
        # Channel-only auth: tunnel-client presents a local secret to the loopback
        # engine, so ChatGPT connects through the Tunnel without OAuth/Tailscale.
        bearer = self.directory / "channel-bearer"
        if not bearer.is_file() or len(bearer.read_text(encoding="utf-8").strip()) < 32:
            bearer.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        environment["MYCOMP_CHANNEL_AUTH"] = "Bearer " + bearer.read_text(encoding="utf-8").strip()
        channel_header = ["--mcp.extra-headers", "Authorization: env:MYCOMP_CHANNEL_AUTH",
                          "--mcp.discovery-extra-headers", "Authorization: env:MYCOMP_CHANNEL_AUTH"]
        # The local MCP origin and the public OAuth authorization-server origin
        # differ. Current tunnel-client versions deny cross-origin discovery
        # unless the exact HTTPS origin was explicitly configured by this app.
        origin = self._configured_oauth_origin()
        if origin:
            environment["MCP_OAUTH_TRUSTED_ORIGINS"] = origin
            environment["HARPOON_OAUTH_FORWARD_ORIGINS"] = origin
            local_binding = urlsplit(self.mcp_endpoint)
            if local_binding.scheme == "http" and local_binding.hostname in {"127.0.0.1", "::1"}:
                # OAuth discovery needs only this owned loopback HTTP MCP target.
                # This is not an anonymous/public MCP endpoint or a generic proxy.
                environment["HARPOON_ALLOW_PLAINTEXT_HTTP"] = "true"
        # ponytail: one owned runtime; use channel-aware profiles if multiple MCP servers are needed.
        self.log = (self.directory / "runtime.log").open("w", encoding="utf-8")
        try:
            self.process = subprocess.Popen([str(self.binary), "run",
                "--control-plane.tunnel-id", config["tunnel_id"],
                "--control-plane.api-key", "env:CONTROL_PLANE_API_KEY",
                "--mcp.server-url", self.mcp_endpoint, *channel_header,
                "--health.listen-addr", "127.0.0.1:0",
                "--health.url-file", str(self.health)],
                env=environment, stdout=self.log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            self.log.close()
            self.log = None
            raise

    def _stop_stale_clients(self):
        """Kill orphaned copies of OUR tunnel-client (e.g. left over from an update),
        so ChatGPT never reaches an old runtime without the channel header."""
        if os.name != "nt":
            return
        path = str(self.binary).replace("'", "''")
        script = ("Get-CimInstance Win32_Process -Filter \"Name='tunnel-client.exe'\" | "
                  f"Where-Object {{ $_.ExecutablePath -eq '{path}' }} | "
                  "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
        try:
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:  # best-effort cleanup must never block starting the tunnel
            pass

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
        """Distinguish control-plane readiness from authenticated MCP tool access."""
        if self.process is None:
            return self.error or "Not connected"
        try:
            base = self.health.read_text(encoding="utf-8").strip()
            if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]+", base):
                return "Starting; waiting for private health URL"
            with urllib.request.urlopen(base + "/api/status", timeout=2) as response:
                if response.status != 200:
                    return "Tunnel control plane not ready"
                payload = json.load(response)
            channels = payload.get("channels", [])
            main = next((item for item in channels if item.get("name") == "main"), None)
            if not main or not main.get("enabled"):
                return "Tunnel connected; MCP main channel disabled"
            probe = main.get("probe_status", "")
            if probe == "auth-required":
                return "Tunnel main connected; OAuth required for MCP probe. Verify authenticated tools/list in ChatGPT"
            if probe in ("failed", "error", "unhealthy"):
                return "Tunnel main MCP probe failed; check runtime.log"
            return "Tunnel main active; verify authenticated ChatGPT tools/list and tool call"
        except (OSError, ValueError, KeyError, TypeError):
            return "Tunnel running; channel status unavailable. Check runtime.log"
