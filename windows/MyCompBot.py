from __future__ import annotations

import ctypes
import json
import os
import queue
import secrets
import shutil
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import uuid
import webbrowser
import winreg
import zlib
from ctypes import wintypes
from pathlib import Path
from tkinter import messagebox, ttk

import pystray
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent.parent
APP_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MyComp Bot"
CONFIG = APP_DATA / ".env"
RUNTIME = APP_DATA / "runtime"
COMMANDS, RESULTS = RUNTIME / "ui-commands", RUNTIME / "ui-results"
LOCAL_HEALTH = "http://127.0.0.1:8645/health"
UI_AUTOMATION_HELPER = Path(__file__).resolve().with_name("UIAutomationBridge.ps1")
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "MyComp Bot"
ISSUE_URL = "https://github.com/apinanautan/mycomp-bot-windows/issues/new?title=MyComp%20Bot%20error"


def _autostart_command() -> str:
    return subprocess.list2cmdline([
        str(ROOT / ".venv" / "Scripts" / "pythonw.exe"),
        str(Path(__file__).resolve()),
    ])


def _autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
            value, _ = winreg.QueryValueEx(key, AUTOSTART_NAME)
        return value == _autostart_command()
    except OSError:
        return False


def _set_autostart(enabled: bool) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_NAME)
            except FileNotFoundError:
                pass


def _read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in CONFIG.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return values


def _write_env(values: dict[str, str]) -> None:
    APP_DATA.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG.with_suffix(".tmp")
    lines = [f"{key}={value}" for key, value in sorted(values.items())]
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(temporary, CONFIG)


def _defaults() -> dict[str, str]:
    home = Path.home()
    return {
        "MYCOMP_ALLOWED_ROOTS": ",".join(str(home / name) for name in ("Documents", "Desktop", "Downloads")),
        "MYCOMP_SCHEMA_VERSION": "4",
        "MYCOMP_PERMISSION_LEVEL": "normal",
        "MYCOMP_AUTH_MODE": "oauth",
        "MYCOMP_PUBLIC_BASE_URL": "",
        "MYCOMP_OAUTH_REDIRECT_URIS": "",
        "MYCOMP_OWNER_CONSENT_TOKEN": secrets.token_urlsafe(32),
        "MYCOMP_ALLOW_SHELL": "true",
        "MYCOMP_ALLOWED_EXECUTABLES": r"C:\Windows\System32\cmd.exe,C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "MYCOMP_SHELL_PATH": r"C:\Windows\System32;C:\Windows;C:\Windows\System32\WindowsPowerShell\v1.0",
        "MYCOMP_SHELL_FOREGROUND_TIMEOUT_SECONDS": "120",
        "MYCOMP_SHELL_AUTO_WAIT_SECONDS": "5",
        "MYCOMP_BROWSER_CDP_ENABLED": "true",
        "MYCOMP_BROWSER_CDP_PORT": "9222",
    }


class WindowsInput:
    """Small, explicit user32 bridge; called only for commands from this app."""

    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
    MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
    MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
    KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)

    def cursor(self) -> dict[str, int]:
        point = wintypes.POINT()
        if not self.user32.GetCursorPos(ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"x": point.x, "y": point.y}

    def move(self, x: float, y: float) -> dict[str, int]:
        if not self.user32.SetCursorPos(round(x), round(y)):
            raise ctypes.WinError(ctypes.get_last_error())
        return self.cursor()

    def mouse(self, flags: tuple[int, ...], x: float | None = None, y: float | None = None) -> dict[str, int]:
        if x is not None and y is not None:
            self.move(x, y)
        for flag in flags:
            self.user32.mouse_event(flag, 0, 0, 0, 0)
        return self.cursor()

    def scroll(self, vertical: int, horizontal: int) -> dict[str, int]:
        if vertical:
            self.user32.mouse_event(self.MOUSEEVENTF_WHEEL, 0, 0, int(vertical), 0)
        if horizontal:
            self.user32.mouse_event(self.MOUSEEVENTF_HWHEEL, 0, 0, int(horizontal), 0)
        return self.cursor()

    def type_text(self, text: str) -> dict[str, int]:
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("union",)
            _fields_ = [("type", wintypes.DWORD), ("union", INPUTUNION)]

        send_input = self.user32.SendInput
        send_input.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        send_input.restype = wintypes.UINT

        # Send UTF-16 code units one at a time. This is slower than one huge
        # SendInput array, but is reliable in modern WinUI/RichEdit controls.
        raw = text.encode("utf-16-le")
        units = [int.from_bytes(raw[index:index + 2], "little") for index in range(0, len(raw), 2)]
        for unit in units:
            events = (INPUT * 2)(
                INPUT(1, INPUTUNION(ki=KEYBDINPUT(0, unit, self.KEYEVENTF_UNICODE, 0, 0))),
                INPUT(1, INPUTUNION(ki=KEYBDINPUT(0, unit, self.KEYEVENTF_UNICODE | self.KEYEVENTF_KEYUP, 0, 0))),
            )
            sent = send_input(2, events, ctypes.sizeof(INPUT))
            if sent != 2:
                raise ctypes.WinError(ctypes.get_last_error())
            time.sleep(0.002)
        return {"characters": len(text), "utf16_units": len(units)}

    def key(self, key: str, modifiers: list[str]) -> dict[str, object]:
        codes = {
            "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12,
            "win": 0x5B, "windows": 0x5B, "meta": 0x5B,
            "enter": 0x0D, "return": 0x0D, "tab": 0x09,
            "escape": 0x1B, "esc": 0x1B, "space": 0x20,
            "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
            "insert": 0x2D, "ins": 0x2D, "home": 0x24, "end": 0x23,
            "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdn": 0x22,
            "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
            "capslock": 0x14, "numlock": 0x90, "scrolllock": 0x91,
            "printscreen": 0x2C, "pause": 0x13,
            "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
            "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
            "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
        }
        normalized = key.lower()
        code = codes.get(normalized, ord(key.upper()) if len(key) == 1 else None)
        if code is None:
            raise ValueError(f"unsupported Windows key: {key}")
        unknown = [item for item in modifiers if item.lower() not in codes]
        if unknown:
            raise ValueError(f"unsupported Windows modifier(s): {', '.join(unknown)}")
        held = [codes[item.lower()] for item in modifiers]
        for item in held:
            self.user32.keybd_event(item, 0, 0, 0)
            time.sleep(0.01)
        self.user32.keybd_event(code, 0, 0, 0)
        time.sleep(0.01)
        self.user32.keybd_event(code, 0, self.KEYEVENTF_KEYUP, 0)
        time.sleep(0.01)
        for item in reversed(held):
            self.user32.keybd_event(item, 0, self.KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)
        return {"key": key, "modifiers": modifiers}

    def windows(self) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(handle, _):
            if not self.user32.IsWindowVisible(handle):
                return True
            length = self.user32.GetWindowTextLengthW(handle)
            if not length:
                return True
            title = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(handle, title, len(title))
            rect = wintypes.RECT()
            self.user32.GetWindowRect(handle, ctypes.byref(rect))
            entries.append({"handle": int(handle), "title": title.value, "bounds": {"x": rect.left, "y": rect.top, "width": rect.right - rect.left, "height": rect.bottom - rect.top}})
            return len(entries) < 100
        self.user32.EnumWindows(callback_type(callback), 0)
        return entries


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class RGBQUAD(ctypes.Structure):
    _fields_ = [("rgbBlue", ctypes.c_ubyte), ("rgbGreen", ctypes.c_ubyte), ("rgbRed", ctypes.c_ubyte), ("rgbReserved", ctypes.c_ubyte)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]


class WindowsCapture:
    """Native Win32 virtual-desktop capture with a dependency-free PNG writer."""

    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
    SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
    SRCCOPY, CAPTUREBLT, DIB_RGB_COLORS = 0x00CC0020, 0x40000000, 0

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.user32.GetDC.argtypes = [wintypes.HWND]
        self.user32.GetDC.restype = wintypes.HDC
        self.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.user32.ReleaseDC.restype = ctypes.c_int
        self.gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self.gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        self.gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self.gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self.gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        self.gdi32.BitBlt.restype = wintypes.BOOL
        self.gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, wintypes.LPVOID, ctypes.POINTER(BITMAPINFO), wintypes.UINT]
        self.gdi32.GetDIBits.restype = ctypes.c_int
        self.gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self.gdi32.DeleteObject.restype = wintypes.BOOL
        self.gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self.gdi32.DeleteDC.restype = wintypes.BOOL

    def desktop_bounds(self) -> dict[str, int]:
        return {
            "x": self.user32.GetSystemMetrics(self.SM_XVIRTUALSCREEN),
            "y": self.user32.GetSystemMetrics(self.SM_YVIRTUALSCREEN),
            "width": self.user32.GetSystemMetrics(self.SM_CXVIRTUALSCREEN),
            "height": self.user32.GetSystemMetrics(self.SM_CYVIRTUALSCREEN),
        }

    @staticmethod
    def _png(width: int, height: int, bgrx: bytes) -> bytes:
        rows = bytearray((width * 4 + 1) * height)
        for row in range(height):
            source, target = row * width * 4, row * (width * 4 + 1)
            rows[target] = 0
            for column in range(width):
                source_offset, target_offset = source + column * 4, target + 1 + column * 4
                rows[target_offset] = bgrx[source_offset + 2]
                rows[target_offset + 1] = bgrx[source_offset + 1]
                rows[target_offset + 2] = bgrx[source_offset]
                rows[target_offset + 3] = 255
        def chunk(name: bytes, value: bytes) -> bytes:
            return struct.pack(">I", len(value)) + name + value + struct.pack(">I", zlib.crc32(name + value) & 0xFFFFFFFF)
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows, level=6)) + chunk(b"IEND", b"")

    def capture(self, region: dict[str, object] | None = None) -> dict[str, object]:
        bounds = self.desktop_bounds()
        requested = region or bounds
        x, y = round(float(requested.get("x", bounds["x"]))), round(float(requested.get("y", bounds["y"])))
        width, height = round(float(requested.get("width", bounds["width"]))), round(float(requested.get("height", bounds["height"])))
        if width < 1 or height < 1 or width * height > 12_000_000:
            raise ValueError("capture region must be between 1 pixel and 12 million pixels")
        screen = self.user32.GetDC(0)
        memory = self.gdi32.CreateCompatibleDC(screen)
        bitmap = self.gdi32.CreateCompatibleBitmap(screen, width, height)
        if not screen or not memory or not bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        old_bitmap = self.gdi32.SelectObject(memory, bitmap)
        try:
            if not self.gdi32.BitBlt(memory, 0, 0, width, height, screen, x, y, self.SRCCOPY | self.CAPTUREBLT):
                raise ctypes.WinError(ctypes.get_last_error())
            info = BITMAPINFO()
            info.bmiHeader = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
            pixels = ctypes.create_string_buffer(width * height * 4)
            copied = self.gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(info), self.DIB_RGB_COLORS)
            if copied != height:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.gdi32.SelectObject(memory, old_bitmap)
            self.gdi32.DeleteObject(bitmap)
            self.gdi32.DeleteDC(memory)
            self.user32.ReleaseDC(0, screen)
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"capture-{uuid.uuid4().hex}.png"
        path.write_bytes(self._png(width, height, pixels.raw))
        return {"path": str(path), "width": width, "height": height, "bounds": {"x": x, "y": y, "width": width, "height": height}, "backend": "win32-bitblt"}


class WindowsUIAutomation:
    """Runs a fixed local UIA helper; MCP-supplied text is JSON data, never code."""

    def execute(self, payload: dict[str, object]) -> dict[str, object]:
        if not UI_AUTOMATION_HELPER.is_file():
            raise RuntimeError("Windows UI Automation helper is missing")
        timeout = min(max(float(payload.get("timeout_seconds", 30)), 0.1), 120)
        process = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-File", str(UI_AUTOMATION_HELPER)],
            input=json.dumps(payload), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        )
        try:
            response = json.loads(process.stdout)
        except json.JSONDecodeError as error:
            detail = process.stderr.strip() or process.stdout.strip() or "Windows UI Automation returned no JSON response"
            raise RuntimeError(detail) from error
        if process.returncode or not response.get("ok"):
            raise RuntimeError(str(response.get("error") or process.stderr.strip() or "Windows UI Automation failed"))
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Windows UI Automation returned an invalid result")
        return result


class MyCompBot(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MyComp Bot for Windows")
        self.minsize(700, 480)
        self.process: subprocess.Popen[str] | None = None
        self.tunnel: subprocess.Popen[str] | None = None
        self.tunnel_queue: queue.Queue[str] = queue.Queue()
        self.temporary_url: str | None = None
        self.input = WindowsInput()
        self.capture = WindowsCapture(RUNTIME / "screenshots")
        self.automation = WindowsUIAutomation()
        values = {**_defaults(), **_read_env()}
        self.owner_consent_token = values["MYCOMP_OWNER_CONSENT_TOKEN"] or secrets.token_urlsafe(32)
        self.domain = tk.StringVar(value=values["MYCOMP_PUBLIC_BASE_URL"])
        self.callback = tk.StringVar(value=values["MYCOMP_OAUTH_REDIRECT_URIS"])
        self.roots = tk.StringVar(value=values["MYCOMP_ALLOWED_ROOTS"])
        self.level = tk.StringVar(value=values["MYCOMP_PERMISSION_LEVEL"])
        self.autostart = tk.BooleanVar(value=_autostart_enabled())
        self.status = tk.StringVar(value="Stopped")
        self.endpoint = tk.StringVar(value="Configure your own public HTTPS domain or start a temporary tunnel.")
        self._build()
        self._refresh_endpoint()
        for directory in (COMMANDS, RESULTS):
            directory.mkdir(parents=True, exist_ok=True)
        self.after(0, self._start)
        self.after(200, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        self._setup_tray()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=18)
        frame.grid(sticky="nsew")
        self.columnconfigure(0, weight=1); self.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="MyComp Bot for Windows", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text="Local MCP engine. No hosted endpoint or shared credentials.").grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 16))
        for row, label, variable in ((2, "Your public HTTPS domain", self.domain), (3, "Your ChatGPT callback URI", self.callback), (4, "Allowed folders (comma separated)", self.roots)):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, columnspan=2, sticky="ew", padx=(12, 0), pady=5)
        ttk.Label(frame, text="Permission profile").grid(row=5, column=0, sticky="w", pady=5)
        ttk.Combobox(frame, textvariable=self.level, values=("normal", "elevated", "full"), state="readonly").grid(row=5, column=1, sticky="w", padx=(12, 0), pady=5)
        ttk.Button(frame, text="Save & Restart", command=self._save_restart).grid(row=5, column=2, sticky="e", pady=5)
        ttk.Separator(frame).grid(row=6, column=0, columnspan=3, sticky="ew", pady=14)
        ttk.Label(frame, text="Local service").grid(row=7, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.status).grid(row=7, column=1, sticky="w", padx=(12, 0))
        ttk.Button(frame, text="Start", command=self._start).grid(row=7, column=2, sticky="e")
        ttk.Button(frame, text="Stop", command=self._stop).grid(row=8, column=2, sticky="e", pady=(6, 0))
        ttk.Label(frame, text="MCP endpoint").grid(row=9, column=0, sticky="nw", pady=(14, 0))
        ttk.Label(frame, textvariable=self.endpoint, wraplength=470).grid(row=9, column=1, sticky="w", padx=(12, 0), pady=(14, 0))
        ttk.Button(frame, text="Copy", command=self._copy_endpoint).grid(row=9, column=2, sticky="e", pady=(14, 0))
        ttk.Button(frame, text="Start Free Temporary Tunnel", command=self._start_tunnel).grid(row=10, column=1, sticky="w", pady=(12, 0))
        ttk.Button(frame, text="Stop Tunnel", command=self._stop_tunnel).grid(row=10, column=2, sticky="e", pady=(12, 0))
        ttk.Button(frame, text="Open ChatGPT Plugins & Copy MCP URL", command=self._open_chatgpt_plugins).grid(row=11, column=1, sticky="w", pady=(12, 0))
        ttk.Button(frame, text="Copy Owner Consent Code", command=self._copy_owner_consent_code).grid(row=11, column=2, sticky="e", pady=(12, 0))
        ttk.Checkbutton(frame, text="Start MyComp Bot automatically when I sign in to Windows", variable=self.autostart, command=self._toggle_autostart).grid(row=12, column=0, columnspan=3, sticky="w", pady=(18, 0))
        ttk.Label(frame, text="Mouse/keyboard actions require Elevated. Accessibility uses Windows UI Automation; screen capture uses native Win32 capture. OCR is intentionally unavailable for now.", wraplength=640).grid(row=13, column=0, columnspan=3, sticky="w", pady=(12, 0))

    def _values(self) -> dict[str, str]:
        return {**_defaults(), **_read_env(), "MYCOMP_OWNER_CONSENT_TOKEN": self.owner_consent_token, "MYCOMP_PUBLIC_BASE_URL": self.domain.get().strip(), "MYCOMP_OAUTH_REDIRECT_URIS": self.callback.get().strip(), "MYCOMP_ALLOWED_ROOTS": self.roots.get().strip(), "MYCOMP_PERMISSION_LEVEL": self.level.get(), "MYCOMP_UI_CAPABILITY": "windows_ui"}

    def _save_restart(self) -> None:
        _write_env(self._values()); self._refresh_endpoint()
        if self.process and self.process.poll() is None:
            self._stop(); self._start()

    def _toggle_autostart(self) -> None:
        try:
            _set_autostart(self.autostart.get())
        except OSError as exc:
            self.autostart.set(_autostart_enabled())
            messagebox.showerror("Windows startup", f"Could not update Windows startup: {exc}")

    def _engine_env(self) -> dict[str, str]:
        values = self._values()
        if self.temporary_url:
            values["MYCOMP_PUBLIC_BASE_URL"] = self.temporary_url
        return {**os.environ, **values, "PYTHONPATH": str(ROOT / "src"), "MYCOMP_DATA_DIR": str(APP_DATA), "MYCOMP_CONFIG_DIR": str(APP_DATA), "MYCOMP_CAPABILITY_DIR": str(APP_DATA / "capabilities"), "MYCOMP_MAINTAINED_CAPABILITIES_DIR": str(ROOT / "capability_sources"), "MYCOMP_UI_CAPABILITY": "windows_ui"}

    def _start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        executable = ROOT / ".venv" / "Scripts" / "python.exe"
        if not executable.exists():
            messagebox.showerror("Setup required", "Run windows\\Run MyComp Bot.ps1 first.")
            return
        self.process = subprocess.Popen([str(executable), "-B", "-m", "mycomp_bot_engine.server"], cwd=ROOT, env=self._engine_env(), text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW))
        self.status.set("Starting…")

    def _stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill()
        self.process = None; self.status.set("Stopped")

    def _refresh_endpoint(self) -> None:
        origin = self.temporary_url or self.domain.get().strip()
        self.endpoint.set(f"{origin.rstrip('/')}/mcp" if origin else "Configure your own public HTTPS domain or start a temporary tunnel.")

    def _copy_endpoint(self) -> None:
        text = self.endpoint.get()
        if text.startswith("http"):
            self.clipboard_clear(); self.clipboard_append(text); self.update()
            return
        messagebox.showinfo("Set up a public MCP URL first", "ChatGPT can only reach a public HTTPS endpoint. Enter your public HTTPS domain or start a Free Temporary Tunnel, then copy the /mcp URL.")

    def _open_chatgpt_plugins(self) -> None:
        self._copy_endpoint()
        if self.endpoint.get().startswith("http"):
            webbrowser.open("https://chatgpt.com/plugins")

    def _copy_owner_consent_code(self) -> None:
        self.clipboard_clear(); self.clipboard_append(self.owner_consent_token); self.update()
        messagebox.showinfo("Owner consent code copied", "Paste this code only on the MyComp Bot authorization page.")

    def _start_tunnel(self) -> None:
        if self.tunnel and self.tunnel.poll() is None:
            return
        cloudflared = shutil.which("cloudflared") or self._values().get("MYCOMP_CLOUDFLARED")
        if not cloudflared:
            messagebox.showerror("cloudflared not found", "Install cloudflared yourself, then make it available on PATH.")
            return
        self._start()
        self.tunnel = subprocess.Popen([cloudflared, "tunnel", "--url", "http://127.0.0.1:8645"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW))
        threading.Thread(target=self._read_tunnel, daemon=True).start()

    def _read_tunnel(self) -> None:
        assert self.tunnel and self.tunnel.stdout
        for line in self.tunnel.stdout:
            self.tunnel_queue.put(line)

    def _stop_tunnel(self) -> None:
        if self.tunnel and self.tunnel.poll() is None:
            self.tunnel.terminate()
        self.tunnel = None
        if self.temporary_url:
            self.temporary_url = None; self._refresh_endpoint()
            if self.process and self.process.poll() is None:
                self._stop(); self._start()

    def _poll(self) -> None:
        try:
            while True:
                line = self.tunnel_queue.get_nowait()
                marker = "https://"
                if marker in line and ".trycloudflare.com" in line:
                    url = marker + line.split(marker, 1)[1].split()[0].rstrip(".,)")
                    if url.endswith(".trycloudflare.com") and url != self.temporary_url:
                        self.temporary_url = url; self._refresh_endpoint(); self._stop(); self._start()
        except queue.Empty:
            pass
        for command in list(COMMANDS.glob("*.json"))[:20]:
            try:
                payload = json.loads(command.read_text(encoding="utf-8")); result = {"ok": True, "result": self._execute_ui(payload)}
            except Exception as error:
                result = {"ok": False, "error": str(error)}
            target = RESULTS / command.name
            target.write_text(json.dumps(result), encoding="utf-8")
            command.unlink(missing_ok=True)
        try:
            with urllib.request.urlopen(LOCAL_HEALTH, timeout=0.2) as response:
                healthy = response.status == 200
        except Exception:
            healthy = False
        if self.process and self.process.poll() is not None:
            self.status.set("Engine stopped unexpectedly")
        elif healthy:
            self.status.set("Running on 127.0.0.1:8645")
        self.after(200, self._poll)

    def _execute_ui(self, payload: dict[str, object]) -> dict[str, object]:
        action = str(payload.get("action")); x, y = payload.get("x"), payload.get("y")
        if action == "launch_app":
            target = str(payload.get("path") or payload.get("app") or payload.get("name") or "").strip()
            if not target:
                raise ValueError("launch_app requires path, app, or name")
            arguments = [str(item) for item in payload.get("arguments", [])]
            process = subprocess.Popen([target, *arguments], cwd=str(payload.get("cwd") or ROOT), creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            return {"launched": True, "process_id": process.pid, "target": target, "arguments": arguments}
        uia_actions = {"status", "list_windows", "observe", "observe_summary", "observe_changes", "inspect_elements", "find_element", "focus", "activate_app", "set_value", "menu_select", "set_window_frame", "close_window", "minimize_window"}
        if action in uia_actions or (action == "click" and x is None and y is None): return self.automation.execute(payload)
        if action == "mouse_move": return self.input.move(float(x), float(y))
        if action == "click": return self.input.mouse((WindowsInput.MOUSEEVENTF_LEFTDOWN, WindowsInput.MOUSEEVENTF_LEFTUP), float(x), float(y))
        if action == "double_click": return self.input.mouse((WindowsInput.MOUSEEVENTF_LEFTDOWN, WindowsInput.MOUSEEVENTF_LEFTUP, WindowsInput.MOUSEEVENTF_LEFTDOWN, WindowsInput.MOUSEEVENTF_LEFTUP), float(x), float(y))
        if action == "right_click": return self.input.mouse((WindowsInput.MOUSEEVENTF_RIGHTDOWN, WindowsInput.MOUSEEVENTF_RIGHTUP), float(x), float(y))
        if action == "scroll": return self.input.scroll(int(payload.get("vertical", 0)), int(payload.get("horizontal", 0)))
        if action == "drag":
            start, end = dict(payload["from"]), dict(payload["to"])
            self.input.move(float(start["x"]), float(start["y"])); self.input.mouse((WindowsInput.MOUSEEVENTF_LEFTDOWN,)); time.sleep(min(max(float(payload.get("duration_seconds", 0.4)), 0), 5)); return self.input.mouse((WindowsInput.MOUSEEVENTF_LEFTUP,), float(end["x"]), float(end["y"]))
        if action == "type_text":
            return self.input.type_text(str(payload.get("text", "")))
        if action == "paste_text":
            text = str(payload.get("text", ""))
            restore = bool(payload.get("restore_clipboard", True))
            previous_text = None
            had_text = False
            try:
                previous_text = self.clipboard_get()
                had_text = True
            except Exception:
                pass
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update()
            time.sleep(0.08)
            self.input.key("v", ["ctrl"])
            time.sleep(0.20)
            if restore:
                self.clipboard_clear()
                if had_text and previous_text is not None:
                    self.clipboard_append(previous_text)
                self.update()
            return {
                "characters": len(text),
                "clipboard_restored": bool(restore and had_text),
            }
        if action in {"press_key", "hotkey"}:
            return self.input.key(str(payload.get("key", "")), [str(item) for item in payload.get("modifiers", [])])
        if action == "capture_display": return self.capture.capture()
        if action == "capture_region": return self.capture.capture(dict(payload.get("region") or {}))
        if action == "capture_window": raise ValueError("capture_window is not implemented in the Windows host yet")
        if action == "ocr":
            capture = self.capture.capture(dict(payload.get("region") or {}) or None)
            from rapidocr_onnxruntime import RapidOCR
            engine = getattr(self, "_ocr_engine", None)
            if engine is None:
                engine = RapidOCR()
                self._ocr_engine = engine
            results, _ = engine(capture["path"])
            needle = str(payload.get("text") or "")
            exact = bool(payload.get("exact", False))
            minimum = float(payload.get("min_confidence", 0) or 0)
            ox, oy = int(capture["bounds"]["x"]), int(capture["bounds"]["y"])
            items = []
            for entry in results or []:
                box, text, score = entry
                if float(score) < minimum:
                    continue
                if needle and ((text != needle) if exact else (needle.lower() not in text.lower())):
                    continue
                xs = [float(point[0]) for point in box]; ys = [float(point[1]) for point in box]
                left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
                items.append({"text": text, "confidence": float(score), "bounds": {"x": round(ox + left), "y": round(oy + top), "width": round(right-left), "height": round(bottom-top)}, "center": {"x": round(ox + (left+right)/2), "y": round(oy + (top+bottom)/2)}})
            return {"backend": "rapidocr-onnxruntime", "items": items, "count": len(items), "capture": capture}
        raise ValueError(f"unsupported Windows desktop action: {action}")

    def _tray_image(self) -> Image.Image:
        image = Image.new("RGB", (64, 64), "#1f2937")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill="#2563eb")
        draw.text((18, 18), "MC", fill="white")
        return image

    def _setup_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("Open MyComp Bot", lambda icon, item: self.after(0, self._show_from_tray), default=True),
            pystray.MenuItem("Report Error on GitHub", lambda icon, item: webbrowser.open(ISSUE_URL)),
            pystray.MenuItem("Exit", lambda icon, item: self.after(0, self._quit)),
        )
        self.tray_icon = pystray.Icon("MyCompBot", self._tray_image(), "MyComp Bot - Running", menu)
        self.tray_icon.run_detached()

    def _hide_to_tray(self) -> None:
        self.withdraw()

    def _show_from_tray(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()
    def _quit(self) -> None:
        self._stop_tunnel(); self._stop(); self.destroy()


if __name__ == "__main__":
    MyCompBot().mainloop()
