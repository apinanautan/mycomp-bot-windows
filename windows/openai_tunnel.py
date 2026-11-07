"""Per-user tunnel settings. Secrets use Windows DPAPI, never source/config text."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.request


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

        return f"""# MyComp Bot — Tailscale เชื่อมเองก่อน แล้วให้ ChatGPT จัดการทุกขั้นตอนที่เหลือจนเสร็จ

ชื่อระบบและปลั๊กอินหลัก: {name}
Windows เครื่องเป้าหมาย: {machine}
โปรเจกต์/Skills: https://github.com/apinanautan/mycomp-bot-windows
OpenAI Tunnel Client: https://github.com/openai/tunnel-client
MCP upstream ตัวอย่างที่ต้องตรวจจากเครื่องจริง: http://127.0.0.1:8645/mcp

**จุดเริ่มต้นที่ผู้ใช้ทำเองเรียบร้อยแล้ว:** ผู้ใช้ติดตั้ง/เชื่อมต่อ Tailscale กับ ChatGPT บัญชีนี้ด้วยตัวเองแล้ว อย่าเริ่มติดตั้ง Tailscale ซ้ำ อย่าขอให้ผู้ใช้ทำขั้นตอนนี้อีก ให้เรียกใช้ปลั๊กอิน Tailscale ที่เชื่อมอยู่เพื่อเข้าถึง Windows และทำงานที่เหลือให้จบ

**ภารกิจ:** ทำงานจริงบนคอมพิวเตอร์ผ่าน Tailscale เป็นช่องทางเริ่มต้น ตรวจของเดิมก่อนทุกขั้นตอน ข้ามขั้นตอนที่ทำเสร็จและใช้งานได้แล้ว ติดตั้งหรือแก้เฉพาะส่วนที่ยังขาด จากนั้นสร้าง/เชื่อม Dino Tunnel (หรือ {name} Tunnel) เพื่อให้เป็นช่องทางหลักที่รวดเร็วขึ้นเมื่อพิสูจน์ว่าใช้งานได้จริง ให้ Tailscale เป็นทางสำรอง ห้ามจบเพียงเขียนคู่มือ พรอมต์ใหม่ หรือรายงานโดยยังไม่ลงมือ

STEP 0 — สำรวจระบบและสิทธิ์ (เริ่มทันที ไม่ต้องถามชื่อซ้ำ)
1. ใช้ Tailscale ที่เชื่อมไว้แล้ว เรียก read-only tool ตรวจ Windows hostname ให้ตรงกับ {machine}, รุ่น MyComp Bot ที่กำลังรัน, local MCP, Git repository, AGENTS.md, STATE.md, git status และบริการที่กำลังทำงาน
2. ตรวจปลั๊กอินและสิทธิ์ที่มีใน ChatGPT จริง: Tailscale, OpenAI Secure MCP Tunnel, Remote Desktop Commander, Plugin Creator และทักษะที่มีอยู่ อย่าอ้างว่าเครื่องมือใดมีสิทธิ์ถ้ายังไม่ตรวจ
3. ห้าม reset/stash/overwrite งานใน repository ที่แก้ค้างอยู่ ห้าม restart งานที่กำลังทำหรือปิด Chrome โดยไม่จำเป็น

STEP 1 — ตรวจ Chrome และ OpenAI Platform โดยใช้เซสชันเดิม
1. ใช้ Chrome หน้าต่างและโปรไฟล์ที่เปิดอยู่จริง หากจำเป็นให้ใช้ agent-desktop หรือ Remote Desktop Commander ที่มีสิทธิ์เข้าถึง ตรวจหน้า https://platform.openai.com/settings/organization/tunnels และ https://platform.openai.com/settings/organization/api-keys
2. ตรวจ Organization, Project และ ChatGPT Workspace ที่จะผูก Tunnel ให้ตรงกับบัญชีเป้าหมาย อย่าเดา Workspace จาก Organization เพียงอย่างเดียว
3. ตรวจ Tunnel ID, client และ key ที่มีอยู่ก่อน หากใช้งานได้และอยู่ในบัญชี/Workspace ที่ถูกต้องให้ใช้ต่อ หากไม่มีหรือเป็นของบัญชีอื่นจึงสร้างใหม่โดยแยกโปรไฟล์ ไม่เขียนทับหรือยึดสิทธิ์ของบัญชีเดิม
4. หากต้องใช้สิทธิ์ล็อกอิน/อนุมัติ/สร้าง API key ให้ผู้ใช้อนุมัติเฉพาะจุดนั้น แล้วดำเนินขั้นตอนถัดไปต่อทันที ไม่ให้ผู้ใช้ต้องเริ่มพรอมต์ใหม่

STEP 2 — จัดการ OpenAI Secure MCP Tunnel / Channel
1. ตรวจ Tunnel Client ทางการและ config ปัจจุบันก่อนติดตั้งใหม่; ถ้าจำเป็นจึงสร้าง Tunnel ใน Organization/Workspace เป้าหมายตามสิทธิ์จริง
2. สร้าง API key เฉพาะ runtime ด้วยสิทธิ์ขั้นต่ำ Tunnels Read+Use หากยังไม่มีที่ใช้ได้ ผู้ใช้กรอก key ผ่านช่องลับในคอมพิวเตอร์เท่านั้น เก็บด้วย Windows DPAPI ห้ามพิมพ์ secret ในแชท/URL/log
3. ตั้ง MCP upstream จากค่าจริง (โดยปกติ http://127.0.0.1:8645/mcp), OAuth และโปรไฟล์ที่แยกจากของเดิม ตรวจ healthz, readyz, /api/status, main channel และ authenticated MCP tools/list พร้อม read-only tool call จริง
4. สร้างหรือปรับปลั๊กอิน {name} Tunnel ด้วย Connection: Tunnel ตามสิทธิ์ของ ChatGPT/Plugin Creator และ Tunnel ID ที่ยืนยันแล้ว ไม่ใช้ Tailscale Funnel เป็นทางวิ่งของ Tunnel ถ้าไม่จำเป็น
5. เมื่อ Tunnel/main ใช้งานจริงและเร็วกว่า ให้ใช้เป็นช่องทางหลักสำหรับ shell, filesystem, git, tests และ API; Tailscale เป็น fallback. ห้ามเปิด Harpoon หากไม่มี target/เหตุผลที่ชัดเจน

STEP 3 — Remote Desktop Commander และงาน GUI
1. ตรวจ agent/process, who_am_i, list_devices และ Device ID ของ Remote Desktop Commander เท่าที่เครื่องมือรองรับ ตรวจว่าบัญชีที่เชื่อมควบคุมเครื่อง {machine} ได้จริง
2. ถ้ามีตัวที่ใช้ได้แล้ว ให้คงไว้และใช้ต่อ หากยังไม่มีให้ติดตั้ง/จับคู่ผ่านขั้นตอนที่ผู้ใช้อนุมัติ โดยไม่ logout หรือลบบัญชีเดิม และไม่อ้างว่าการมีโปรเซสเท่ากับเชื่อมบัญชีสำเร็จ
3. ตรวจ agent-desktop, list-windows, snapshot และทดสอบ GUI แบบปลอดภัย; อย่าเปิด Chrome โปรไฟล์ใหม่หรือปิดเซสชันที่ล็อกอินอยู่

STEP 4 — ปลั๊กอิน ชื่อ ไอคอน และ Skills
1. ตรวจปลั๊กอิน {name} Tailscale, {name} Tunnel และ Remote Desktop Commander ที่มีอยู่แล้วก่อนสร้างซ้ำ เปลี่ยนชื่อ/metadata เฉพาะปลั๊กอินที่ผู้ใช้เป็นเจ้าของและแพลตฟอร์มอนุญาต
2. ใช้ไอคอนต้นฉบับของ MyComp Bot จาก windows/assets/mycomp-bot.png หรือ .ico ถ้ามีและแพลตฟอร์มรองรับ ห้ามสร้างปลั๊กอินหลอกหรืออ้างว่าเปลี่ยนไอคอนสำเร็จโดยไม่ได้ตรวจผล
3. ตรวจและติดตั้ง/แนบ Skills: development-loop, ponytail, agent-desktop-portable, connection-recovery, tool-routing รวม LICENSE/PLAYBOOK ที่เกี่ยวข้องจาก repository; ข้ามสิ่งที่ติดตั้งถูกต้องแล้ว
4. ปรับ routing และ recovery ให้ Tunnel/main เป็นหลักหลังตรวจผ่าน, Tailscale เป็น fallback และ Remote Desktop Commander/agent-desktop สำหรับ GUI ตามความเหมาะสม

STEP 5 — ทดสอบจริง แก้ปัญหา และทำต่อจนเสร็จ
1. ทดสอบ Engine, OAuth, Tailscale, Tunnel/main, MCP tools/list และ read-only tool call จริง รวม MCP filesystem, batch_read, diagnostics ถ้า Engine รุ่นนี้รองรับ; ตรวจ Remote Desktop Commander, Chrome GUI, Skills, icon/metadata และระบบเริ่มทำงานใหม่; ตรวจความเร็วและความเสถียรจริง ไม่เดาจาก HTTP 200 เพียงอย่างเดียว
2. ทดสอบ Windows unit/integration tests แยกปัญหาทดสอบเก่าหรือ POSIX-only จากบั๊กจริง แก้เท่าที่เกี่ยวข้องโดยไม่ทำลายงานเดิม
3. บันทึก checkpoint ใน STATE.md ระบุสิ่งที่ทำจริง สิ่งที่ข้ามเพราะมีแล้ว หลักฐานทดสอบ และสิ่งที่ยังรอสิทธิ์ โดยไม่บันทึก secret
4. ทำขั้นตอนถัดไปอัตโนมัติในเซสชันเดียวกันจนหมดงานที่มีสิทธิ์ทำ หากต้องรอการอนุมัติให้ถามเฉพาะจุดนั้น แล้วทำต่อ ไม่วนกลับไปขอให้เชื่อม Tailscale อีก
5. สรุปสถานะเป็น สำเร็จจริง / รอการอนุมัติ / ไม่รองรับ / ยังทดสอบไม่ผ่าน โดยไม่กล่าวอ้าง 100% หากมีข้อค้าง

กฎสำคัญ: ผู้ใช้เชื่อม Tailscale เองแล้วเท่านั้นที่เป็นเงื่อนไขเริ่มงาน อย่าติดตั้งซ้ำ ไม่สร้าง ZIP เป็นขั้นแรก ไม่เปลี่ยน Tunnel ID/API key/บัญชีที่ใช้งานได้โดยพลการ ไม่ลด OAuth ไม่เปิด public MCP แบบไม่มีการยืนยันตัวตน ไม่เผยแพร่ Release หรือแก้ Git history โดยไม่มีคำสั่งเฉพาะ ทำงานต่อเนื่องให้มากที่สุดภายใต้สิทธิ์และเครื่องมือจริง"""

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
                "--mcp.server-url", self.mcp_endpoint,
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
