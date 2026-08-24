from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_APP_DATA = Path(os.getenv("MYCOMP_DATA_DIR", Path.home() / "AppData/Local/MyComp Bot"))
_CONFIG = _APP_DATA / ".env"
_DEFAULT_PROFILE = _APP_DATA / "browser-profile"
_DISPLAY_STATE = _APP_DATA / "runtime/display-state.json"


def _settings() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for raw in _CONFIG.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    except FileNotFoundError:
        pass
    return values



def _display(payload: dict[str, Any]) -> dict[str, Any] | None:
    settings = _settings()
    requested = str(payload.get("display_id", settings.get("MYCOMP_UI_DEFAULT_DISPLAY", "bot"))).strip().lower()
    try:
        state = json.loads(_DISPLAY_STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    displays = [item for item in state.get("displays", []) if isinstance(item, dict)]
    if requested in {"", "bot", "auto"}:
        target_id = str(state.get("bot_display_id") or "")
        return next((item for item in displays if str(item.get("id")) == target_id), None)
    if requested == "main":
        return next((item for item in displays if item.get("is_main") is True), None)
    return next((item for item in displays if str(item.get("id")) == requested), None)


def _window_arguments(display: dict[str, Any] | None) -> list[str]:
    if not display:
        return []
    bounds = display.get("bounds") or {}
    try:
        x, y = int(float(bounds["x"])), int(float(bounds["y"]))
        width, height = int(float(bounds["width"])), int(float(bounds["height"]))
    except (KeyError, TypeError, ValueError):
        return []
    return [
        f"--window-position={x + 12},{y + 36}",
        f"--window-size={max(width - 24, 640)},{max(height - 48, 480)}",
    ]

def _port(payload: dict[str, Any]) -> int:
    settings = _settings()
    port = int(payload.get("port", settings.get("MYCOMP_BROWSER_CDP_PORT", "9222")))
    if not 9222 <= port <= 9322:
        raise ValueError("CDP port must be between 9222 and 9322")
    return port


def _enabled() -> bool:
    value = _settings().get("MYCOMP_BROWSER_CDP_ENABLED", "true").lower()
    return value in {"1", "true", "yes", "on"}


def _json_request(port: int, path: str, method: str = "GET") -> Any:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(request, timeout=3) as response:
        if response.status != 200:
            raise RuntimeError(f"CDP HTTP {response.status}")
        body = response.read(2_000_000)
        if not body:
            return True
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return body.decode("utf-8", errors="replace")


def _tabs(port: int) -> list[dict[str, Any]]:
    return [item for item in _json_request(port, "/json/list") if item.get("type") == "page"]


def _tab(port: int, payload: dict[str, Any]) -> dict[str, Any]:
    tabs = _tabs(port)
    tab_id = payload.get("tab_id")
    if tab_id:
        for item in tabs:
            if item.get("id") == tab_id:
                return item
        raise KeyError("tab not found")
    index = int(payload.get("tab_index", 0))
    if not tabs or not 0 <= index < len(tabs):
        raise KeyError("no matching browser tab")
    return tabs[index]


class CDPWebSocket:
    def __init__(self, url: str, timeout: float = 10) -> None:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("only local ws:// CDP endpoints are allowed")
        self.sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port or 80}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode("ascii"))
        response = self._read_http_headers()
        if not response.startswith("HTTP/1.1 101"):
            raise RuntimeError(f"CDP websocket handshake failed: {response.splitlines()[0] if response else 'empty response'}")
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if f"sec-websocket-accept: {accept}".lower() not in response.lower():
            raise RuntimeError("CDP websocket handshake response is invalid")
        self.next_id = 1

    def _read_http_headers(self) -> str:
        data = bytearray()
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk or len(data) + len(chunk) > 64_000:
                break
            data.extend(chunk)
        return data.decode("latin1")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _send_frame(self, data: bytes, opcode: int = 1) -> None:
        first = 0x80 | opcode
        mask = os.urandom(4)
        length = len(data)
        if length < 126:
            header = bytes([first, 0x80 | length])
        elif length < 65536:
            header = bytes([first, 0x80 | 126]) + struct.pack("!H", length)
        else:
            header = bytes([first, 0x80 | 127]) + struct.pack("!Q", length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self.sock.sendall(header + mask + masked)

    def _recv_exact(self, count: int) -> bytes:
        data = bytearray()
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise ConnectionError("CDP websocket closed")
            data.extend(chunk)
        return bytes(data)

    def _recv_frame(self) -> tuple[int, bytes]:
        first, second = self._recv_exact(2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        if length > 32_000_000:
            raise ValueError("CDP websocket frame is too large")
        mask = self._recv_exact(4) if second & 0x80 else None
        payload = self._recv_exact(length)
        if mask:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self.next_id
        self.next_id += 1
        self._send_frame(json.dumps({"id": request_id, "method": method, "params": params or {}}, separators=(",", ":")).encode())
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 8:
                raise ConnectionError("CDP websocket closed")
            if opcode == 9:
                self._send_frame(payload, opcode=10)
                continue
            if opcode != 1:
                continue
            message = json.loads(payload)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(message["error"].get("message", "CDP command failed"))
            return message.get("result", {})


def _with_tab(payload: dict[str, Any], callback):
    port = _port(payload)
    tab = _tab(port, payload)
    socket_client = CDPWebSocket(tab["webSocketDebuggerUrl"], timeout=float(payload.get("timeout_seconds", 10)))
    try:
        return callback(socket_client, tab)
    finally:
        socket_client.close()


def _evaluate(client: CDPWebSocket, expression: str, await_promise: bool = True) -> Any:
    result = client.call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": await_promise, "userGesture": True})
    if result.get("exceptionDetails"):
        raise RuntimeError(result["exceptionDetails"].get("text", "JavaScript evaluation failed"))
    return result.get("result", {}).get("value")


def _selector_script(selector: str, body: str) -> str:
    return f"""(() => {{ const el = document.querySelector({json.dumps(selector)}); if (!el) return {{ok:false,error:'not found'}}; {body} }})()"""


def execute(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if not _enabled():
        raise PermissionError("browser CDP control is disabled in MyComp Bot settings")
    action = str(payload.get("action", "status"))
    port = _port(payload)

    if action == "launch":
        profile_raw = str(payload.get("profile", _settings().get("MYCOMP_BROWSER_PROFILE", _DEFAULT_PROFILE)))
        profile = Path(os.path.expandvars(profile_raw)).expanduser()
        profile.mkdir(parents=True, exist_ok=True)
        url = str(payload.get("url", "about:blank"))
        display = _display(payload)
        arguments = ["--headless=new", "--disable-gpu", "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check", "--enable-logging", "--log-file=C:/mycomp-chrome-debug.log"]
        if os.name == "nt":
            candidates = [
                Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe",
                Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
                Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
            ]
            chrome = next((item for item in candidates if item.is_file()), None)
            if chrome is None:
                raise FileNotFoundError("Google Chrome was not found; install it or use the browser's existing CDP port")
            subprocess.Popen([str(chrome), *arguments], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        else:
            subprocess.run(["/usr/bin/open", "-na", "Google Chrome", "--args", *arguments], check=True, timeout=15)
        deadline = time.monotonic() + float(payload.get("timeout_seconds", 15))
        while time.monotonic() < deadline:
            try:
                version = _json_request(port, "/json/version")
                return {"launched": True, "port": port, "profile": str(profile), "browser": version.get("Browser"), "websocket": version.get("webSocketDebuggerUrl"), "display": display}
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)
        raise TimeoutError("Chrome CDP did not become ready")

    if action == "status":
        try:
            version = _json_request(port, "/json/version")
            return {"ready": True, "port": port, "browser": version.get("Browser"), "tabs": len(_tabs(port))}
        except (OSError, urllib.error.URLError):
            return {"ready": False, "port": port}

    if action == "list_tabs":
        return {"tabs": [{key: item.get(key) for key in ("id", "title", "url", "type", "webSocketDebuggerUrl")} for item in _tabs(port)]}

    if action == "new_tab":
        url = urllib.parse.quote(str(payload.get("url", "about:blank")), safe=":/?&=#")
        return _json_request(port, "/json/new?" + url, method="PUT")

    if action == "close_tab":
        tab = _tab(port, payload)
        return {"closed": bool(_json_request(port, f"/json/close/{tab['id']}")), "tab_id": tab["id"]}

    if action == "navigate":
        url = str(payload["url"])
        return _with_tab(payload, lambda client, tab: {"tab_id": tab["id"], **client.call("Page.navigate", {"url": url})})

    if action == "evaluate":
        return _with_tab(payload, lambda client, tab: {"tab_id": tab["id"], "value": _evaluate(client, str(payload["expression"]))})

    if action == "query":
        selector = str(payload["selector"])
        script = _selector_script(selector, "const r=el.getBoundingClientRect(); return {ok:true,text:el.innerText||el.value||'',tag:el.tagName,disabled:!!el.disabled,frame:{x:r.x,y:r.y,width:r.width,height:r.height}};")
        return _with_tab(payload, lambda client, tab: {"tab_id": tab["id"], **(_evaluate(client, script) or {})})

    if action == "click":
        selector = str(payload["selector"])
        script = _selector_script(selector, "el.scrollIntoView({block:'center',inline:'center'}); el.click(); return {ok:true};")
        result = _with_tab(payload, lambda client, tab: {"tab_id": tab["id"], **(_evaluate(client, script) or {})})
        if not result.get("ok"):
            raise KeyError(f"DOM selector not found: {selector}")
        return result

    if action == "type":
        selector, text = str(payload["selector"]), str(payload.get("text", ""))
        script = _selector_script(selector, f"el.focus(); const setter=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el),'value')?.set; if(setter) setter.call(el,{json.dumps(text)}); else el.value={json.dumps(text)}; el.dispatchEvent(new Event('input',{{bubbles:true}})); el.dispatchEvent(new Event('change',{{bubbles:true}})); return {{ok:true,value:el.value}};")
        result = _with_tab(payload, lambda client, tab: {"tab_id": tab["id"], **(_evaluate(client, script) or {})})
        if not result.get("ok"):
            raise KeyError(f"DOM selector not found: {selector}")
        return result

    if action == "wait":
        timeout = min(max(float(payload.get("timeout_seconds", 30)), 0), 300)
        interval = min(max(float(payload.get("poll_interval_seconds", 0.2)), 0.05), 2)
        selector = payload.get("selector")
        expression = payload.get("expression")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if selector:
                    value = _with_tab(payload, lambda client, tab: _evaluate(client, f"!!document.querySelector({json.dumps(str(selector))})"))
                elif expression:
                    value = _with_tab(payload, lambda client, tab: _evaluate(client, str(expression)))
                else:
                    raise ValueError("wait requires selector or expression")
                if value:
                    return {"matched": True, "value": value}
            except (ConnectionError, RuntimeError, urllib.error.URLError):
                pass
            time.sleep(interval)
        return {"matched": False, "timed_out": True, "timeout_seconds": timeout}

    if action == "screenshot":
        destination = Path(str(payload.get("path", Path.home() / "Downloads/browser-screenshot.png"))).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        def capture(client, tab):
            client.call("Page.enable")
            result = client.call("Page.captureScreenshot", {"format": str(payload.get("format", "png")), "fromSurface": True, "captureBeyondViewport": bool(payload.get("full_page", False))})
            destination.write_bytes(base64.b64decode(result["data"], validate=True))
            return {"path": str(destination), "bytes": destination.stat().st_size, "tab_id": tab["id"]}
        return _with_tab(payload, capture)

    raise ValueError(f"unsupported browser CDP action: {action}")


def self_test():
    assert urllib.parse.urlparse("ws://127.0.0.1:9222/devtools/page/x").hostname == "127.0.0.1"
    assert _selector_script("#x", "return {ok:true};").startswith("(() =>")
    return True
