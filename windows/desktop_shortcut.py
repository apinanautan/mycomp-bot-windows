"""Idempotent desktop shortcut installation; never touch other apps."""
from __future__ import annotations

import ctypes
from pathlib import Path


def windows_desktop_directory() -> Path:
    """Resolve redirected/OneDrive Desktop rather than assuming ~/Desktop."""
    if not hasattr(ctypes, "windll"):
        return Path.home() / "Desktop"
    buffer = ctypes.create_unicode_buffer(32768)
    try:
        result = ctypes.windll.shell32.SHGetFolderPathW(
            None, 0x0010, None, 0, buffer
        )  # CSIDL_DESKTOPDIRECTORY
        if result == 0 and buffer.value:
            return Path(buffer.value)
    except (AttributeError, OSError):
        pass
    return Path.home() / "Desktop"


def ensure_desktop_shortcut(root: Path, *, desktop: Path | None = None) -> str:
    """Create only a missing MyComp Bot.lnk, or repair our own icon.

    Returns 'created', 'present', or 'conflict'.  Never overwrites a
    shortcut pointing to another application or another app installation.
    """
    from win32com.client import Dispatch

    root = Path(root).resolve()
    exe = root / ".venv/Scripts/pythonw.exe"
    script = root / "windows/MyCompBot.py"
    icon = root / "windows/assets/mycomp-bot.ico"
    if not exe.is_file() or not script.is_file() or not icon.is_file():
        raise FileNotFoundError("MyComp Bot executable, script, or icon is missing")

    desktop = Path(desktop) if desktop is not None else windows_desktop_directory()
    if not desktop.is_dir():
        raise FileNotFoundError(f"Windows Desktop folder not found: {desktop}")
    path = desktop / "MyComp Bot.lnk"
    shell = Dispatch("WScript.Shell")
    link = shell.CreateShortcut(str(path))

    if path.exists():
        current_exe = str(link.TargetPath or "")
        current_script = str(link.Arguments or "")
        if (Path(current_exe).resolve() != exe.resolve() or
                str(script).casefold() not in current_script.casefold()):
            return "conflict"
        current_icon = str(link.IconLocation or "")
        if not current_icon or (
            current_icon.replace("/", "\\").casefold().endswith(
                "\\windows\\assets\\mycomp-bot.ico,0"
            )
        ):
            if current_icon.casefold() != f"{icon},0".casefold():
                link.IconLocation = f"{icon},0"
                link.Save()
        return "present"

    link.TargetPath = str(exe)
    link.Arguments = f'"{script}"'
    link.WorkingDirectory = str(root)
    link.IconLocation = f"{icon},0"
    link.Description = "Launch MyComp Bot"
    link.Save()
    if not path.is_file():
        raise RuntimeError("Windows did not create the MyComp Bot desktop shortcut")
    return "created"
