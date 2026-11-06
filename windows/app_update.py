"""GitHub release updates. This helper also runs outside the app directory."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
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


def managed_release_root(source: Path, app_data: Path) -> Path:
    """A versioned installation that never writes inside a Git checkout."""
    source = source.resolve()
    version = (source / "VERSION").read_text(encoding="utf-8").strip()
    version_tuple(version)
    target = app_data.resolve() / "versions" / f"v{version}"
    if target == source or target in source.parents or source in target.parents:
        raise ValueError("Managed installation must be outside update staging")
    return target


def install_managed_release(
    source: Path, app_data: Path, base_python: Path, log,
    *, install=install_dependencies,
) -> Path:
    """Install a new immutable app copy; never overlay the original source.

    A completed copy can be reused. An incomplete destination is never
    overwritten or silently deleted because it might contain user data.
    """
    source = source.resolve()
    target = managed_release_root(source, app_data)
    if target.exists():
        if target.is_symlink() or not (target / ".mycomp-install-complete").is_file():
            raise RuntimeError(f"Managed destination exists but is incomplete: {target}")
        if not (target / ".venv/Scripts/pythonw.exe").is_file():
            raise RuntimeError(f"Managed destination is missing its Python environment: {target}")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or not target.parent.resolve().is_relative_to(app_data.resolve()):
        raise ValueError("Managed install directory escapes the app data folder")
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError("Release source contains a symbolic link")
        if path.is_file() and any(part in PROTECTED for part in path.relative_to(source).parts):
            raise ValueError("Protected file inside release source")
    try:
        shutil.copytree(source, target)
        subprocess.run(
            [str(base_python), "-m", "venv", str(target / ".venv")],
            check=True, stdout=log, stderr=subprocess.STDOUT, timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        install(target, log)
        if not (target / ".venv/Scripts/pythonw.exe").is_file():
            raise RuntimeError("Managed app Python launcher was not installed")
        (target / ".mycomp-install-complete").write_text(
            (source / "VERSION").read_text(encoding="utf-8").strip(),
            encoding="utf-8",
        )
        return target
    except Exception:
        # Only delete our new, private version directory, never the checkout.
        if target.exists():
            remove_temporary(target, target.parent)
        raise


def redirect_launchers(previous: Path, installed: Path, log) -> None:
    """Update only MyComp shortcuts pointing at this old app installation."""
    previous, installed = previous.resolve(), installed.resolve()
    if previous == installed:
        return
    old_exe = str(previous / ".venv/Scripts/pythonw.exe")
    old_script = str(previous / "windows/MyCompBot.py")
    new_exe = str(installed / ".venv/Scripts/pythonw.exe")
    new_script = str(installed / "windows/MyCompBot.py")
    icon = str(installed / "windows/assets/mycomp-bot.ico")
    def quote_ps(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    ps = (
        "$ErrorActionPreference='Stop';"
        "$shell=New-Object -ComObject WScript.Shell;"
        "$links=@("
        "[IO.Path]::Combine([Environment]::GetFolderPath('Desktop'),'MyComp Bot.lnk'),"
        "[IO.Path]::Combine([Environment]::GetFolderPath('Programs'),'MyComp Bot.lnk'),"
        "[IO.Path]::Combine($env:APPDATA,'Microsoft\\Internet Explorer\\Quick Launch\\User Pinned\\TaskBar\\MyComp Bot.lnk')"
        ");"
        f"$oldExe={quote_ps(old_exe)};$oldScript={quote_ps(old_script)};"
        f"$newExe={quote_ps(new_exe)};$newScript={quote_ps(new_script)};"
        f"$newRoot={quote_ps(str(installed))};$newIcon={quote_ps(icon)};"
        "foreach($linkPath in $links){"
        "if(-not (Test-Path -LiteralPath $linkPath)){continue};"
        "$link=$shell.CreateShortcut($linkPath);"
        "if($link.TargetPath -ine $oldExe -or "
        "$link.Arguments.IndexOf($oldScript,[StringComparison]::OrdinalIgnoreCase) -lt 0){continue};"
        "$link.TargetPath=$newExe;$link.Arguments='"'+$newScript+'"';"
        "$link.WorkingDirectory=$newRoot;$link.IconLocation=$newIcon+',0';$link.Save()"
        "}"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
         __import__("base64").b64encode(ps.encode("utf-16le")).decode("ascii")],
        capture_output=True, text=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        print(f"Shortcut migration warning: {result.stderr.strip()}", file=log, flush=True)

    if os.name == "nt":
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
                current, kind = winreg.QueryValueEx(key, "MyComp Bot")
                if kind == winreg.REG_SZ and old_exe.casefold() in current.casefold() and old_script.casefold() in current.casefold():
                    new_command = subprocess.list2cmdline([new_exe, new_script])
                    winreg.SetValueEx(key, "MyComp Bot", 0, winreg.REG_SZ, new_command)
        except FileNotFoundError:
            pass


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
    parent_exited = False
    with args.log.open("a", encoding="utf-8") as log:
        try:
            # The user has already confirmed the update in the application.
            # Never replace Git source files, even when the working tree is clean.
            wait_for_parent(args.parent_pid)
            parent_exited = True
            destination = install_managed_release(
                args.source, args.log.parent, Path(sys.executable), log,
            )
            print(f"Installed isolated app copy: {destination}", file=log, flush=True)
            process = restart(destination)
            for _ in range(60):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8645/health", timeout=1) as response:
                        health = json.load(response)
                    if process.poll() is None and health.get("status") == "ok" and health.get("service") == "mycomp-bot":
                        running = True
                        break
                except Exception:
                    pass
                if process.poll() is not None:
                    break
                time.sleep(0.5)
            if not running:
                if process.poll() is None:
                    subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, timeout=15,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                raise RuntimeError("Updated app did not become healthy; the original checkout was not modified")
            try:
                redirect_launchers(args.root, destination, log)
            except Exception as warning:
                print(f"Launcher migration warning: {warning}", file=log, flush=True)
            print(f"Update installed successfully: {destination}", file=log, flush=True)
        except Exception as error:
            print(f"Update failed: {error}", file=log, flush=True)
            ctypes.windll.user32.MessageBoxW(None, f"Update failed: {error}\nLog: {args.log}", "MyComp Bot update", 0x10)
        finally:
            if parent_exited and not running:
                restart(args.root)


if __name__ == "__main__":
    main()
