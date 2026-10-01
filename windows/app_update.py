"""GitHub release updates. This helper also runs outside the app directory."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPOSITORY = "apinanautan/mycomp-bot-windows"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
PROTECTED = {".git", ".venv", ".env", "oauth-state", "logs"}


def remove_temporary(path: Path, parent: Path) -> None:
    if path.is_symlink() or path.resolve().parent != parent.resolve():
        raise ValueError("Temporary cleanup path leaves its expected directory")
    shutil.rmtree(path)


def version_tuple(version: str) -> tuple[int, ...]:
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", version):
        raise ValueError(f"Unsupported release version: {version}")
    return tuple(int(part) for part in version.lstrip("v").split("."))


def latest_release() -> dict[str, str]:
    request = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "MyComp-Bot-Updater",
    })
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    tag = str(data["tag_name"])
    version_tuple(tag)
    if data.get("draft") or data.get("prerelease"):
        raise ValueError("Only published stable releases can be installed")
    return {"tag": tag, "url": f"https://github.com/{REPOSITORY}/archive/refs/tags/{tag}.zip"}


def prepare_update(release: dict[str, str], updates: Path) -> Path:
    tag = release["tag"]
    version_tuple(tag)
    expected_url = f"https://github.com/{REPOSITORY}/archive/refs/tags/{tag}.zip"
    if release["url"] != expected_url:
        raise ValueError("Unexpected release archive URL")
    updates.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="stage-", dir=updates))
    archive = stage / "release.zip"
    try:
        request = urllib.request.Request(expected_url, headers={"User-Agent": "MyComp-Bot-Updater"})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as output:
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise ValueError("Release archive exceeds the download limit")
                output.write(chunk)
        source = extract_release(archive, stage / "source", tag)
        archive.unlink()
        return source
    except Exception:
        remove_temporary(stage, updates)
        raise


def extract_release(archive: Path, destination: Path, tag: str) -> Path:
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        total = sum(item.file_size for item in members)
        if total > MAX_ARCHIVE_BYTES or len(members) > 10000:
            raise ValueError("Release archive exceeds extraction limits")
        roots = set()
        for item in members:
            path = PurePosixPath(item.filename)
            if not path.parts or path.is_absolute() or ".." in path.parts or "\\" in item.filename or ":" in item.filename:
                raise ValueError("Unsafe path in release archive")
            roots.add(path.parts[0])
            if any(part in PROTECTED for part in path.parts) or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Protected file or symbolic link in release archive")
        if len(roots) != 1:
            raise ValueError("Release archive must have one source directory")
        bundle.extractall(destination)
    source = destination / roots.pop()
    for name in ("windows/MyCompBot.py", "windows/app_update.py", "requirements.lock", "pyproject.toml", "VERSION"):
        if not (source / name).is_file():
            raise ValueError(f"Incomplete release archive: {name}")
    if version_tuple((source / "VERSION").read_text().strip()) != version_tuple(tag):
        raise ValueError("Release version does not match its archive")
    return source


def check_checkout(root: Path) -> None:
    if (root / ".git").exists():
        git = shutil.which("git")
        if not git:
            raise RuntimeError("This is a Git checkout. Install a separate app copy to use automatic updates.")
        result = subprocess.run([git, "-C", str(root), "status", "--porcelain"], capture_output=True, text=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=15)
        if result.returncode or result.stdout.strip():
            raise RuntimeError("This source checkout has local changes. Save them before updating, or update an installed app copy.")


def install_dependencies(root: Path, log) -> None:
    python = root / ".venv/Scripts/python.exe"
    for arguments in (["-m", "pip", "install", "--require-hashes", "-r", str(root / "requirements.lock")],
                      ["-m", "pip", "install", "--no-deps", str(root)]):
        subprocess.run([str(python), *arguments], cwd=root, stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def apply_files(root: Path, source: Path, log, install=install_dependencies) -> None:
    """Overlay release files; preserve unrelated files and restore changed files on error."""
    root, source = root.resolve(), source.resolve()
    check_checkout(root)
    if root == source or root in source.parents or source in root.parents:
        raise ValueError("Update staging must be outside the app directory")
    files = [path for path in source.rglob("*") if path.is_file()]
    for path in files:
        relative = path.relative_to(source)
        if path.is_symlink() or any(part in PROTECTED for part in relative.parts):
            raise ValueError("Protected file in update source")
        target = root / relative
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise ValueError("Update destination leaves the app directory")
    backup = Path(tempfile.mkdtemp(prefix="backup-", dir=source.parent))
    changed = []
    try:
        for path in files:
            relative = path.relative_to(source)
            target = root / relative
            existed = target.exists()
            if existed:
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            changed.append((relative, existed))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        install(root, log)
    except Exception:
        for relative, existed in reversed(changed):
            target = root / relative
            if existed:
                shutil.copy2(backup / relative, target)
            else:
                target.unlink(missing_ok=True)
        # A failed dependency upgrade may have changed the environment too.
        try:
            install(root, log)
        except Exception as rollback_error:
            print(f"Dependency rollback failed: {rollback_error}", file=log, flush=True)
        raise
    finally:
        remove_temporary(backup, source.parent)


def wait_for_parent(pid: int) -> None:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if handle:
        try:
            if kernel.WaitForSingleObject(handle, 90000) != 0:
                raise RuntimeError("MyComp Bot did not exit in time; update was cancelled")
        finally:
            kernel.CloseHandle(handle)


def restart(root: Path):
    return subprocess.Popen([str(root / ".venv/Scripts/pythonw.exe"), str(root / "windows/MyCompBot.py")],
                            cwd=root, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--parent-pid", required=True, type=int)
    parser.add_argument("--log", required=True, type=Path)
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    running = False
    def install_and_restart(root: Path, log) -> None:
        nonlocal running
        install_dependencies(root, log)
        process = restart(root)
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8645/health", timeout=1) as response:
                    health = json.load(response)
                if process.poll() is None and health.get("status") == "ok" and health.get("service") == "mycomp-bot":
                    running = True
                    return
            except Exception:
                pass
            if process.poll() is not None:
                break
            time.sleep(0.5)
        if process.poll() is None:
            subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        raise RuntimeError("Updated app did not become healthy; restoring the previous files")
    with args.log.open("a", encoding="utf-8") as log:
        try:
            wait_for_parent(args.parent_pid)
            print(f"Updating {args.root}", file=log, flush=True)
            apply_files(args.root, args.source, log, install=install_and_restart)
            print("Update installed successfully", file=log, flush=True)
        except Exception as error:
            print(f"Update failed: {error}", file=log, flush=True)
            ctypes.windll.user32.MessageBoxW(None, f"Update failed: {error}\nLog: {args.log}", "MyComp Bot update", 0x10)
        finally:
            if not running:
                restart(args.root)


if __name__ == "__main__":
    main()
