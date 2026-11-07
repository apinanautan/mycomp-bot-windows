"""Non-secret, user-copyable MyComp Bot plugin setup fields."""
from __future__ import annotations

import re


def base_name(value: str) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 70 or any(ord(ch) < 32 for ch in value):
        raise ValueError("กรุณาตั้งชื่อหลัก 1–70 ตัวอักษร")
    return value


def copy_value(kind: str, name: str, tunnel_settings: dict) -> str:
    """Never expose secret credentials or fabricate Channel IDs."""
    if kind == "tailscale_name":
        return base_name(name) + " Tailscale"
    if kind == "tunnel_name":
        return base_name(name) + " Tunnel"
    if kind == "tunnel_id":
        value = str(tunnel_settings.get("tunnel_id") or "").strip()
        if not re.fullmatch(r"tunnel_[a-f0-9]{32}", value):
            raise ValueError("ยังไม่มี Tunnel ID ที่บันทึกและตรวจรูปแบบผ่าน")
        return value
    if kind == "channel_name":
        # Local tunnel-client's primary channel is named main; this is NOT a
        # platform-generated Channel ID.
        return "main"
    if kind == "channel_id":
        value = str(tunnel_settings.get("channel_id") or "").strip()
        if not value:
            raise ValueError(
                "โปรแกรมยังไม่ได้รับ Channel ID จาก OpenAI Platform "
                "(main เป็นชื่อ Channel ไม่ใช่ Channel ID)"
            )
        if len(value) > 256 or any(ord(ch) < 33 for ch in value):
            raise ValueError("Channel ID ที่บันทึกไม่ถูกต้อง")
        return value
    raise ValueError("ไม่รู้จักชนิดข้อมูลที่จะคัดลอก")
