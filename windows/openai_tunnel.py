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

**สกิลประจำงาน (สำคัญ):** อ่านและใช้ skills/operator-clarity/SKILL.md จากโปรเจกต์นี้ก่อนทำงานทุกครั้ง เพื่อยืนยันว่าคุยถึงเครื่องไหน ชื่อหลักอะไร งานไหนต้องทำ งานไหนต้องข้าม และอย่าไปยุ่งกับปลั๊กอิน Studio/Orchestrator ที่ไม่เกี่ยวข้อง ถ้าติดสิทธิ์ Custom MCP ให้ข้ามเฉพาะการผูก Tunnel ฝั่ง ChatGPT โดยทำงานอิสระอื่นต่อได้

**ภารกิจ:** ทำงานจริงบนคอมพิวเตอร์ผ่าน Tailscale เป็นช่องทางเริ่มต้น ตรวจของเดิมก่อนทุกขั้นตอน ข้ามขั้นตอนที่ทำเสร็จและใช้งานได้แล้ว ติดตั้งหรือแก้เฉพาะส่วนที่ยังขาด จากนั้นสร้าง/เชื่อม Dino Tunnel (หรือ {name} Tunnel) เพื่อให้เป็นช่องทางหลักที่รวดเร็วขึ้นเมื่อพิสูจน์ว่าใช้งานได้จริง ให้ Tailscale เป็นทางสำรอง ห้ามจบเพียงเขียนคู่มือ พรอมต์ใหม่ หรือรายงานโดยยังไม่ลงมือ

STEP 0 — ใช้ Tailscale ที่เชื่อมแล้วตรวจเครื่องอย่างย่อ
1. Tailscale เชื่อมกับ ChatGPT ไว้แล้ว ห้ามติดตั้งหรือขอให้เชื่อมซ้ำ ให้ตรวจ hostname {machine}, Engine, และ Tunnel ที่มีอยู่ด้วยคำสั่งอ่านอย่างปลอดภัยเท่านั้น
2. ใช้ชื่อหลักที่ผู้ใช้กรอกในหน้าต่างโปรแกรมนี้ คือ {name} เป็นแหล่งชื่อเดียวตลอดกระบวนการ ชื่อที่ต้องการของสองปลั๊กอินคือ "{name} Tailscale" และ "{name} Tunnel" ห้ามตั้งชื่อจาก hostname หรือชื่อแอปอื่นเอง
3. ห้ามแตะต้อง เปลี่ยนชื่อ อัปเดต หรือสร้าง Tidmunz Studio, Studio AI, Orchestrator, Operator, ระบบของบุคคลอื่น หรือแอปอื่นที่ไม่ใช่ MyComp Bot แม้จะพบอยู่ในบัญชีเดียวกัน

STEP 1 — ทำ OpenAI Secure MCP Tunnel ให้เสร็จก่อน (สำคัญสูงสุด)

**กฎข้ามงานที่ทำเสร็จแล้ว — ห้ามทำใหม่เพื่อความเร็วและความปลอดภัย:**
- ตรวจไฟล์/สถานะที่ MyComp Bot บันทึกไว้ก่อน: saved Tunnel ID, named Tunnel profile, key.dpapi (ตรวจเพียงว่ามีและถอดรหัสใช้ได้ในเครื่องเท่านั้น ห้ามแสดง/คัดลอก secret), client, MCP upstream และ main channel; คำว่า "บันทึกแล้ว" ไม่จำเป็นต้องหมายถึง "เชื่อมต่อสำเร็จ"
- หาก Tunnel ID, API Key และ main Channel มีอยู่และ ChatGPT เรียก MCP ผ่าน Tunnel ได้จริง ให้ทำเครื่องหมาย "เสร็จแล้ว/ข้าม" ทันที **ห้ามสร้าง Tunnel, Channel, Key, OAuth client หรือโปรไฟล์ใหม่ซ้ำ และห้ามเปิดหน้า Platform เพื่อสร้างของใหม่**
- ถ้ามีค่าบันทึกไว้แต่ connection/test ไม่ผ่าน ให้ตรวจสาเหตุและซ่อมเฉพาะจุดเดิม เช่น client ไม่รัน, main disabled, OAuth ผิด, endpoint ไม่ตรง หรือไฟร์วอลล์ ห้ามรีเซ็ต key, ล้างโปรไฟล์, สร้างของใหม่โดยไม่จำเป็น
- สร้างองค์ประกอบใหม่เฉพาะเมื่อพิสูจน์ได้ว่าขาด/ใช้ไม่ได้จริงและผู้ใช้อนุมัติสิทธิ์ที่เกี่ยวข้อง; หลังตรวจผ่านให้ข้ามไปตั้งชื่อปลั๊กอินและจัดหน้าจอทันที
- ขั้นตอนอื่นก็ใช้หลักเดียวกัน: ตรวจว่าทำแล้วหรือไม่, ผ่านให้ข้าม, แก้เฉพาะที่ยังไม่ผ่าน; อย่าติดตั้งใหม่, ตั้งค่าใหม่ หรือทดสอบซ้ำเกินจำเป็น

1. ตรวจ Tunnel Client, Tunnel ID, main channel, OAuth, โปรไฟล์ และ API key ที่มีอยู่บนเครื่องผ่าน Tailscale ก่อน ถ้าใช้งานได้อยู่แล้วให้คงเดิม
2. หากต้องเข้า OpenAI Platform ให้ใช้เบราว์เซอร์ทำงานแยกจาก ChatGPT (ไม่ย้ายแท็บแชท) ตรวจ Organization, Project, Workspace จริง; ห้ามสร้าง Tunnel ซ้ำและห้ามเปลี่ยนบัญชีที่ใช้ได้โดยพลการ
3. ถ้าจำเป็นต้องสร้าง Tunnel/Key ใหม่ให้ใช้สิทธิ์ขั้นต่ำตามที่มีจริง เก็บ key ด้วย Windows DPAPI ในเครื่อง ห้ามแสดง secret ในแชท URL หรือ log
4. ทำ Tunnel/main และปลั๊กอิน "{name} Tunnel" ให้เชื่อมกับ ChatGPT Workspace จริง ทดสอบ authenticated MCP tools/list และการเรียก read-only diagnostics จริงผ่าน Tunnel; ห้ามถือว่าโปรเซสทำงานหรือ HTTP 200 คือเสร็จ
5. เมื่อ Tunnel ใช้งานได้แล้ว ใช้ Tunnel เป็นช่องทางหลัก และให้ Tailscale เป็น fallback ไม่เปลี่ยน route ของบริการอื่น ไม่ทำคำสั่งที่เปลี่ยนสถานะซ้ำโดยไม่ตรวจผล
6. ถ้าต้องรอผู้ใช้ล็อกอินหรืออนุมัติ ให้แจ้งเฉพาะจุดที่ต้องการ แต่ยังทำขั้นตอนที่เป็นอิสระและปลอดภัยผ่าน Tailscale ได้ โดยไม่สร้าง key หรือ Tunnel ใหม่ซ้ำ
7. ถ้าพิสูจน์ว่าบัญชี/Workspace ไม่มีสิทธิ์เชื่อม Custom MCP ให้รายงาน blocked_permission เฉพาะการเชื่อม ChatGPT เข้ากับ Tunnel; เก็บ Tunnel ID, DPAPI key, Channel และโปรไฟล์เดิมไว้ แล้วไปทำขั้นตอนตั้งชื่อปลั๊กอินที่แก้ได้, หน้าจอ, Skills และทดสอบท้องถิ่นให้ครบผ่าน Tailscale โดยไม่อ้างว่า Tunnel พร้อมบน ChatGPT

STEP 2 — ตั้งชื่อปลั๊กอิน Tailscale และ Tunnel ให้ตรงกัน (หลัง Tunnel พร้อม)
0. แยกผลสองชั้นเสมอ: การอัปเดตไฟล์/เวอร์ชันของ Private Plugin ใน Plugin Creator ไม่เท่ากับการติดตั้งหรือเปิดใช้ปลั๊กอินในบัญชี/Workspace ChatGPT; ตรวจรายการ Installed Plugins ของบัญชีจริงก่อนรายงานว่าปลั๊กอินปรากฏแล้ว ถ้าชื่อถูกเปลี่ยนในแพ็กเกจแต่ Installed Plugins ยังเป็นชื่อเดิม ให้รายงานสองผลแยก ไม่อ้างว่ามองเห็นแล้ว
1. อ่านชื่อที่เลือกไว้ในพรอมต์นี้จาก {name}: ชื่อปลั๊กอินที่ต้องการคือ "{name} Tailscale" และ "{name} Tunnel" เท่านั้น ตรวจชื่อปัจจุบันกับ Plugin Creator/รายการแอปและเจ้าของจริงก่อนแก้
2. ถ้าปลั๊กอิน Tailscale เดิมตั้งชื่อมั่วไว้ชั่วคราว และเป็นปลั๊กอินที่ผู้ใช้เป็นเจ้าของและแก้ชื่อได้ ให้เปลี่ยนชื่อเดิมเป็น "{name} Tailscale" โดยรักษาการเชื่อมต่อ MCP และสิทธิ์เดิมไว้; ทำเช่นเดียวกันกับปลั๊กอิน Tunnel ให้ชื่อเป็น "{name} Tunnel"
3. ถ้าแพลตฟอร์มไม่อนุญาตให้แก้ชื่อแอปหรือปลั๊กอินเดิมโดยตรง ต้องบอกชื่อเดิมที่พบ เหตุผลที่เปลี่ยนไม่ได้ และทางเลือกที่รองรับ ห้ามอ้างว่าเปลี่ยนชื่อแล้ว ห้ามติดตั้งซ้ำ ลบ หรือสร้างสำเนาเพื่อกลบปัญหาโดยไม่ถาม
4. อย่าสับสนระหว่างชื่อโหนด Tailscale, ชื่อปลั๊กอินใน ChatGPT, ชื่อ App Connector หรือชื่อระบบ Orchestrator: แก้เฉพาะชนิดและรายการที่ตรงกับ MyComp Bot; ห้ามเปลี่ยนชื่อแอปอื่นเพราะมีคำว่า Studio, Tailscale หรือชื่อเครื่องอยู่

STEP 3 — หน้าจอเดียวแบ่งครึ่ง ChatGPT ซ้าย / Chrome ทำงานขวา
1. ใช้จอ Windows จอเดียวแบ่งสองหน้าต่างข้างกัน ไม่ใช่สองมอนิเตอร์: ChatGPT/แชทเดิมครึ่งซ้าย และ dedicated Google Chrome สำหรับ AI ทำงานครึ่งขวา ต้องเห็นกิจกรรมได้จริง
2. ห้ามนำทาง รีเฟรช ปิด เปลี่ยน URL ย้ายแท็บ หรือล็อกเอาต์ ChatGPT เดิม ถ้าต้องจัดหน้าต่างให้ใช้ Windows Accessibility เลือกหน้าต่าง ChatGPT ที่ตรวจสอบตัวตนได้แล้วปรับขนาดเฉพาะหน้าต่างนั้น หาก ChatGPT เปิดบนมือถือไม่ต้องเปิดหน้าใหม่บน PC
3. ใช้ dom_cdp.launch เปิด Chrome แบบมีหน้าต่าง (ไม่ใช่ headless) ด้วย profile/port แยกต่างหากที่ครึ่งขวา และตรวจว่ามองเห็นได้จริง ไม่ปิดหรือใช้ Chrome ส่วนตัวของผู้ใช้
4. ใช้แท็บทำงานเดิมทีละงาน นำทาง URL ด้วย dom_cdp.navigate เท่านั้น ตรวจผลลัพธ์ก่อนเปลี่ยนงาน อย่าเปิดแท็บหรือหน้าต่างใหม่เรื่อย ๆ ถ้าจำเป็นให้ปิดแท็บชั่วคราวเมื่องานเสร็จ
5. ห้ามใช้ webbrowser.open, Start-Process URL, os.startfile, cmd start หรือเบราว์เซอร์เริ่มต้นสำหรับเปิดลิงก์งาน เพราะจะรบกวนแชทเดิม

STEP 4 — ส่วนที่เหลือของ MyComp Bot
1. ตรวจ Remote Desktop Commander/agent-desktop, Windows Accessibility, keyboard, mouse, vision และ Chrome CDP ด้วยคำสั่งจริง โดยไม่แตะบริการ Studio ที่ไม่เกี่ยวข้อง
2. ตรวจ Skills (รวม operator-clarity, development-loop, ponytail, tool-routing, connection-recovery, agent-desktop-portable), ไอคอน MyComp Bot และระบบเริ่มพร้อม Windows; สร้างหรือปรับเฉพาะรายการที่ยังขาด ใช้ชื่อหลัก {name} อย่างสม่ำเสมอ
3. ห้ามเปลี่ยนชื่อปลั๊กอินหรือแอปที่ไม่เกี่ยวข้อง ห้ามเปิดลิงก์บนหน้าต่าง ChatGPT ที่ผู้ใช้อ่านอยู่

STEP 5 — ตรวจรับและรายงานตรงตามจริง
0. แยกการตรวจรับ local Tunnel Client / main channel / สิทธิ์ Workspace / authenticated tools/list ใน ChatGPT ให้เป็นคนละผลเสมอ ห้ามบันทึกว่า Tunnel เชื่อม ChatGPT สำเร็จเพราะเรียก Tailscale แล้วผ่าน
1. ตรวจ Tunnel/main, OAuth, ChatGPT authenticated tools/list และการเรียก diagnostics ผ่าน OpenAI Tunnel จริง แล้วจึงตรวจ Tailscale fallback
2. ทดสอบการแบ่งครึ่งหน้าจอและการใช้ Chrome แยกโดยนำทางในแท็บงานเดิม ตรวจว่า ChatGPT ไม่ถูกเปลี่ยนหน้า
3. สรุปผลแยกกันว่า "{name} Tunnel" และ "{name} Tailscale" เปลี่ยนชื่อสำเร็จแล้ว / เปลี่ยนไม่ได้เพราะข้อจำกัด / ยังรอสิทธิ์ อย่ารายงานว่าสำเร็จหากชื่อที่แสดงจริงยังไม่ตรง
4. บันทึก checkpoint ใน STATE.md ไม่ใส่ secret ทำงานต่อเท่าที่มีสิทธิ์โดยไม่ให้ผู้ใช้เริ่ม Tailscale ใหม่

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
