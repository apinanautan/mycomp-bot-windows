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

    @property
    def mcp_endpoint(self) -> str:
        """The exact local binding passed to the Tunnel runtime."""
        return LOCAL_MCP_ENDPOINT

    def plugin_prompt(self, plugin_name: str, tailscale_base: str) -> str:
        """Build both routes from verified, non-secret settings; no secret reads."""
        from urllib.parse import urlsplit, urlunsplit

        name = plugin_name.strip() if isinstance(plugin_name, str) else ""
        if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
            raise ValueError("Enter a plugin name (1–80 characters) before creating a prompt.")
        saved = self.load()
        tunnel_id = validate_tunnel_id(saved.get("tunnel_id"))
        url = urlsplit(tailscale_base.strip() if isinstance(tailscale_base, str) else "")
        if (
            url.scheme != "https" or not url.hostname
            or not url.hostname.endswith(".ts.net")
            or url.username or url.password or url.query or url.fragment
        ):
            raise ValueError("Save a valid Tailscale HTTPS base URL first.")
        try:
            port = url.port or 443
        except ValueError as error:
            raise ValueError("Invalid Tailscale port.") from error
        if port not in {443, 8443, 10000}:
            raise ValueError("Unsupported Tailscale Funnel HTTPS port.")
        tailscale_endpoint = urlunsplit(("https", url.netloc, url.path.rstrip("/") + "/mcp", "", ""))
        endpoint = self.mcp_endpoint
        return (
            f"ชื่อปลั๊กอินที่ผู้ใช้เลือก: {name}\\n"
            "สร้างปลั๊กอินสำหรับ MyComp Bot ที่รองรับการเชื่อมต่อ 2 ช่องทาง "
            "คือ Tailscale และ OpenAI Secure MCP Tunnel โดยตรวจสอบว่าระบบปลั๊กอินรองรับจริงก่อนดำเนินการ\\n\\n"
            f"ช่องทาง Tailscale HTTPS MCP: {tailscale_endpoint}\\n"
            f"ช่องทาง OpenAI Secure MCP Tunnel ID: {tunnel_id}\\n"
            f"Local MCP binding ของ Tunnel runtime: {endpoint}\\n\\n"
            "localhost / 127.0.0.1 เป็นปลายทางภายในเครื่อง Windows เท่านั้น "
            "ChatGPT Cloud ไม่สามารถเรียก URL นี้โดยตรงได้\\n"
            "ตรวจสอบการเข้าถึง Tailscale Funnel จากภายนอกจริง รวมถึง OAuth และเครือข่าย "
            "ห้ามสรุปว่า URL .ts.net เข้าถึงจากคลาวด์ได้เพียงเพราะเป็น HTTPS\\n"
            "ตรวจสอบการรองรับ Secure MCP Tunnel และรูปแบบการผูก Tunnel ID อย่างเป็นทางการ "
            "ห้ามเดา connector URL หรือสร้าง endpoint ปลอม\\n"
            f"ขั้นที่ 1: สร้างปลั๊กอินสองรายการแยกกัน โดยใช้ชื่อ {name} (Tailscale) "
            f"และ {name} (Tunnel) เพื่อเชื่อม MyComp Bot เครื่องเดียวกันจาก Tailscale HTTPS MCP "
            "และ OpenAI Secure MCP Tunnel ตามลำดับ หากแพลตฟอร์มรองรับเส้นทางคู่ในปลั๊กอินเดียว "
            "จะเพิ่มตัวเลือก failover อย่างปลอดภัยก็ได้ แต่ต้องระบุชัดเจนว่าใช้งานจริงในรูปแบบใด\\n"
            "อย่าสร้างตัวเชื่อมต่อซ้ำโดยไม่มีเหตุผล และอย่าสร้างปลั๊กอินหรือ endpoint จำลอง\\n\\n"
            "ทดสอบ MCP tools/list และเรียกเครื่องมืออ่านสถานะที่ปลอดภัยผ่านแต่ละเส้นทางจริง "
            "ก่อนยืนยันว่าพร้อมใช้งาน\\n"
            "ตรวจสอบความล้มเหลวการเชื่อมต่อก่อนสลับเส้นทาง ห้ามสั่งรันซ้ำสำหรับคำสั่ง "
            "ที่แก้ข้อมูลหรือไม่สามารถยืนยันได้ว่าไม่ได้ทำไปแล้ว และห้ามลดระดับการยืนยันตัวตน\\n"
            "รักษา OAuth/authentication และขอบเขตสิทธิ์ของ MyComp Bot เดิม "
            "ห้ามร้องขอหรือแสดง API key, access token, .env หรือความลับในพรอมต์\\n"
            "ขั้นที่ 2: เมื่อสร้างปลั๊กอินทั้งสองสำเร็จและทดสอบเครื่องมืออ่านสถานะได้แล้ว "
            "จึงติดตั้ง agent-desktop ของ vercel-labs บน Windows เครื่องนี้แบบแยกตามเครื่อง "
            "(https://github.com/vercel-labs/agent-desktop) โดยขอความยินยอมจากเจ้าของเครื่องก่อนติดตั้ง "
            "ตรวจ Windows/Node.js/npm และใช้แพ็กเกจทางการที่ตรวจสอบเวอร์ชันได้ "
            "หลีกเลี่ยงการขอสิทธิ์ผู้ดูแลระบบโดยไม่จำเป็น และอย่าลบหรือเขียนทับเครื่องมือเดิม\\n"
            "หลังติดตั้งให้ตรวจ agent-desktop version และ agent-desktop status พร้อมแสดงผลจริง "
            "ถ้า Windows Accessibility, สิทธิ์ไฟล์/ACL หรือ dependency ไม่พร้อมให้รายงานสาเหตุ "
            "และหยุดขั้นตอนที่ทำไม่สำเร็จ ไม่อ้างว่าติดตั้งผ่านแล้ว\\n\\n"
            "ขั้นที่ 3: agent-desktop mcp ให้ MCP ผ่าน stdio ภายในเครื่อง ไม่ใช่ HTTP URL สาธารณะ "
            "ห้ามสร้าง URL ปลอมหรือบอกว่า ChatGPT Cloud เรียก stdio บน Windows ได้โดยตรง "
            "ให้ตรวจว่าระบบ MyComp Bot รองรับการเปิดและกำกับ MCP subprocess/bridge "
            "สำหรับ agent-desktop ได้จริงก่อนเพิ่มเครื่องมือ หากต้องพัฒนา adapter ให้ทำตามระบบอนุญาตเดิม "
            "และยืนยันกับเจ้าของเครื่องก่อนเปิดสิทธิ์ UI control หรือเพิ่มชื่อ MCP tool สาธารณะ\\n"
            "เมื่อ bridge พร้อม ให้เชื่อมการเรียก agent-desktop ผ่าน MyComp Bot ที่ปลั๊กอิน Tailscale "
            "และ Tunnel ใช้ร่วมกัน หรือสร้างปลั๊กอิน Desktop แยกเฉพาะเมื่อแพลตฟอร์มรองรับจริง "
            "และมีการยืนยันตัวตน/สิทธิ์เทียบเท่าเดิม\\n\\n"
            "ขั้นที่ 4: ทดสอบ agent-desktop list-windows, snapshot และการใช้ ref ID "
            "เพื่ออ่าน Accessibility tree ในหน้าต่างทดสอบที่ไม่ใช่ข้อมูลลับ "
            "การคลิกหรือแก้ค่าต้องได้รับอนุญาตตามระดับสิทธิ์ของ MyComp Bot "
            "และต้อง snapshot ใหม่เพื่อตรวจผลหลังทำงาน อย่าใช้ ref เก่าหลัง UI เปลี่ยน "
            "ใช้ screen capture เดิมเป็น fallback เฉพาะเมื่อต้องใช้และได้รับอนุญาต\\n"
            "อธิบายว่า agent-desktop ช่วยค้นหาปุ่ม/ช่องข้อความ/หน้าต่างด้วย Accessibility "
            "และเรียก click/set-value/scroll ผ่าน ref ส่วน MyComp Bot ดูแล MCP/OAuth/สิทธิ์ "
            "รวมถึงบอกข้อจำกัดของแอปที่อ่าน Accessibility ไม่ได้\\n"
            "จัดทำรายงานแยกตามเครื่อง: ปลั๊กอิน Tailscale, ปลั๊กอิน Tunnel, agent-desktop "
            "(ติดตั้งแล้วหรือไม่, เวอร์ชัน, MCP bridge, permission, การทดสอบสำเร็จ/ล้มเหลว) "
            "ห้ามแสดงภาพหน้าจอ ข้อมูลคลิปบอร์ด token หรือข้อมูลส่วนตัวในรายงานสาธารณะ\\n\\n"
            "Runtime ready ไม่ใช่หลักฐานว่า ChatGPT เรียกใช้เครื่องมือสำเร็จ "
            "ต้องแสดงผลการทดสอบ tools/list และการเรียกอ่านสถานะจริง\\n"
            "ถ้าแพลตฟอร์มไม่รองรับปลั๊กอินเส้นทางคู่ ให้แจ้งข้อจำกัดและเสนอรูปแบบ "
            "ที่รองรับจริงเท่านั้น ห้ามอ้างว่ารองรับ failover หรือสร้างปลั๊กอินหลอก"
        ).replace("\\n", "\n")

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
