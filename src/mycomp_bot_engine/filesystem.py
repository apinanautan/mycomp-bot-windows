from __future__ import annotations

import fnmatch
import os
import secrets
import stat
from pathlib import Path
from typing import Any


class Filesystem:
    """Descriptor-relative filesystem operations rooted at configured directories."""

    def __init__(self, roots: tuple[Path, ...], max_read_bytes: int = 1_000_000, max_search_files: int = 1_000, max_list_entries: int = 1_000, max_write_bytes: int | None = None, max_search_directories: int = 1_000, max_search_depth: int = 32, protected_paths: tuple[Path, ...] = ()) -> None:
        self.roots = tuple(root.resolve() for root in roots)
        self.protected_paths = tuple(path.resolve() for path in protected_paths)
        self.max_read_bytes, self.max_search_files, self.max_list_entries = max_read_bytes, max_search_files, max_list_entries
        self.max_write_bytes = max_write_bytes if max_write_bytes is not None else max_read_bytes
        self.max_search_directories, self.max_search_depth = max_search_directories, max_search_depth

    def _is_protected(self, candidate: Path) -> bool:
        # Compare both abspath and fully resolved forms so macOS /var → /private/var
        # (and similar symlink prefixes) cannot slip past control-plane protection.
        forms = {candidate}
        try:
            forms.add(candidate.resolve())
        except OSError:
            pass
        for form in forms:
            for protected in self.protected_paths:
                if form == protected or protected in form.parents:
                    return True
        return False

    def _candidate_path(self, raw: str) -> Path:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            if self.roots:
                candidate = self.roots[0] / candidate
            else:
                candidate = Path.cwd() / candidate
        return Path(os.path.abspath(candidate))

    def _root_and_parts(self, raw: str, *, unrestricted: bool = False) -> tuple[Path, list[str]]:
        candidate = self._candidate_path(raw)
        if self._is_protected(candidate):
            raise PermissionError("path is protected control-plane storage")
        if unrestricted:
            # Full control may reach any non-protected path. Anchor at / so openat
            # still walks components without following intermediate symlinks.
            root = Path("/")
            if candidate == root:
                return root, []
            try:
                relative = candidate.relative_to(root)
            except ValueError as error:
                raise PermissionError("path is outside the local filesystem") from error
            parts = list(relative.parts)
            if any(part in {"", ".", ".."} for part in parts):
                raise PermissionError("invalid path component")
            return root, parts
        if not self.roots:
            raise PermissionError("filesystem is disabled: MYCOMP_ALLOWED_ROOTS is not configured")
        for root in self.roots:
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                continue
            parts = list(relative.parts)
            if any(part in {"", ".", ".."} for part in parts):
                raise PermissionError("invalid path component")
            return root, parts
        raise PermissionError("path is outside configured allowed roots")

    def resolve(self, raw_path: str, *, must_exist: bool = False, unrestricted: bool = False) -> Path:
        if os.name == "nt" and must_exist:
            resolved = self._candidate_path(raw_path).resolve(strict=True)
            if not resolved.is_dir():
                raise NotADirectoryError(resolved)
            if self._is_protected(resolved):
                raise PermissionError("path is protected control-plane storage")
            if not unrestricted and not any(resolved == allowed or allowed in resolved.parents for allowed in self.roots):
                raise PermissionError("path is outside configured allowed roots")
            return resolved
        root, parts = self._root_and_parts(raw_path, unrestricted=unrestricted)
        target = root.joinpath(*parts)
        if must_exist:
            if unrestricted:
                resolved = target.resolve(strict=True)
                if not resolved.is_dir():
                    raise NotADirectoryError(resolved)
                if self._is_protected(resolved):
                    raise PermissionError("path is protected control-plane storage")
                if not unrestricted and not any(resolved == allowed or allowed in resolved.parents for allowed in self.roots):
                    raise PermissionError("path is outside configured allowed roots")
                return resolved
            fd = self._open_target(raw_path, directory=True)
            os.close(fd)
        return target

    def _open_parent(self, raw: str, create: bool = False) -> tuple[int, str, Path]:
        root, parts = self._root_and_parts(raw)
        if not parts: raise PermissionError("operation on an allowed root itself is not permitted")
        if os.name == "nt":
            # ponytail: Windows lacks O_DIRECTORY/dir_fd; use pathlib instead.
            return -1, parts[-1], root.joinpath(*parts)
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                try: next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    if not create: raise
                    os.mkdir(part, 0o700, dir_fd=fd)
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = next_fd
            return fd, parts[-1], root.joinpath(*parts)
        except BaseException:
            os.close(fd); raise

    def _open_target(self, raw: str, directory: bool = False) -> int:
        root, parts = self._root_and_parts(raw)
        if os.name == "nt":
            # ponytail: Windows lacks O_DIRECTORY/dir_fd; return -1 as placeholder fd.
            # Callers must check os.name == "nt" and use Path directly.
            return -1
        if not parts:
            if not directory: raise IsADirectoryError(root)
            return os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        parent, name, _ = self._open_parent(raw)
        try:
            flags = os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if directory else 0)
            return os.open(name, flags, dir_fd=parent)
        finally: os.close(parent)

    def _read(self, raw: str) -> tuple[str, Path]:
        if os.name == "nt":
            resolved = self.resolve(raw, unrestricted=False)
            if not resolved.is_file(): raise ValueError("path is not a regular file")
            if resolved.stat().st_size > self.max_read_bytes: raise ValueError("file exceeds configured read limit")
            return resolved.read_text(encoding="utf-8", errors="replace")[:self.max_read_bytes], resolved
        fd = self._open_target(raw)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode): raise ValueError("path is not a regular file")
            if info.st_size > self.max_read_bytes: raise ValueError("file exceeds configured read limit")
            data = os.read(fd, self.max_read_bytes + 1)
            if len(data) > self.max_read_bytes: raise ValueError("file exceeds configured read limit")
            return data.decode("utf-8"), self.resolve(raw)
        finally: os.close(fd)

    def _write(self, raw: str, content: str) -> str:
        if os.name == "nt":
            if len(content.encode("utf-8")) > self.max_write_bytes: raise ValueError("content exceeds configured write limit")
            resolved = self.resolve(raw, unrestricted=False)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            if resolved.exists() and resolved.is_symlink(): raise PermissionError("refusing to replace a symlink")
            resolved.write_text(content, encoding="utf-8")
            return str(resolved)
        if len(content.encode("utf-8")) > self.max_write_bytes: raise ValueError("content exceeds configured write limit")
        parent, name, display = self._open_parent(raw, create=True)
        temporary = None
        try:
            for _ in range(20):
                temporary = f".{name}.{secrets.token_hex(12)}.tmp"
                try:
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                    break
                except FileExistsError: continue
            else: raise FileExistsError("could not allocate temporary file")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
            try:
                previous = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISLNK(previous.st_mode): raise PermissionError("refusing to replace a symlink")
            except FileNotFoundError: pass
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            temporary = None
            return str(display)
        finally:
            if temporary:
                try: os.unlink(temporary, dir_fd=parent)
                except FileNotFoundError: pass
            os.close(parent)

    @staticmethod
    def _bounded_list(value: Any, name: str, limit: int = 100) -> list[Any]:
        if not isinstance(value, list) or not value: raise ValueError(f"{name} must be a non-empty list")
        if len(value) > limit: raise ValueError(f"{name} exceeds the {limit}-item limit")
        return value

    @staticmethod
    def _matches(relative: Path, include: list[str], exclude: list[str]) -> bool:
        text = relative.as_posix()
        if exclude and any(fnmatch.fnmatchcase(text, pattern) for pattern in exclude): return False
        return not include or any(fnmatch.fnmatchcase(text, pattern) for pattern in include)

    def _search(self, path: str, needle: str, *, detailed: bool, include: list[str], exclude: list[str], max_results: int) -> dict[str, Any]:
        if not needle: raise ValueError("query must not be empty")
        root, parts = self._root_and_parts(path)
        base = root.joinpath(*parts)
        start = self._open_target(path, directory=True)
        matches: list[Any] = []
        inspected = 0
        directories = 0
        truncated = False

        def visit(fd: int, shown: Path, depth: int) -> None:
            nonlocal inspected, directories, truncated
            if depth > self.max_search_depth: truncated = True; return
            with os.scandir(fd) as scan:
                for entry in scan:
                    if inspected >= self.max_search_files or len(matches) >= max_results:
                        truncated = True; return
                    name = entry.name
                    try: info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    except FileNotFoundError: continue
                    item = shown / name
                    if self._is_protected(item): continue
                    relative = item.relative_to(base)
                    if stat.S_ISDIR(info.st_mode):
                        if exclude and any(fnmatch.fnmatchcase(relative.as_posix(), pattern.rstrip("/")) or fnmatch.fnmatchcase((relative / "x").as_posix(), pattern) for pattern in exclude):
                            continue
                        directories += 1
                        if directories > self.max_search_directories: truncated = True; return
                        try: child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                        except OSError: continue
                        try: visit(child, item, depth + 1)
                        finally: os.close(child)
                    elif stat.S_ISREG(info.st_mode):
                        inspected += 1
                        if info.st_size > self.max_read_bytes or not self._matches(relative, include, exclude): continue
                        child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
                        try: text = os.read(child, self.max_read_bytes).decode("utf-8", errors="ignore")
                        finally: os.close(child)
                        if detailed:
                            for line_number, line in enumerate(text.splitlines(), 1):
                                if needle in line:
                                    matches.append({"path": str(item), "relative_path": relative.as_posix(), "line": line_number, "text": line[:500]})
                                    if len(matches) >= max_results: truncated = True; return
                        elif needle in text:
                            matches.append(str(item))

        try: visit(start, base, 0)
        finally: os.close(start)
        return {"matches": matches, "truncated": truncated, "inspected_files": inspected, "inspected_directories": directories}

    def _patch_many(self, changes: Any) -> dict[str, Any]:
        items = self._bounded_list(changes, "changes")
        originals: dict[str, str] = {}
        prepared: dict[str, str] = {}
        ordered_paths: list[str] = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {"path", "old", "new"}: raise ValueError("each change must contain only path, old, and new")
            raw_path, old, new = item["path"], item["old"], item["new"]
            if not isinstance(raw_path, str) or not isinstance(old, str) or not isinstance(new, str) or not old: raise ValueError("change path/old/new must be strings and old must not be empty")
            current, display = self._read(raw_path)
            canonical = str(display)
            if canonical not in originals:
                originals[canonical] = current
                prepared[canonical] = current
                ordered_paths.append(canonical)
            content = prepared[canonical]
            if content.count(old) != 1: raise ValueError(f"patch text must occur exactly once in {raw_path}")
            updated = content.replace(old, new, 1)
            if len(updated.encode("utf-8")) > self.max_write_bytes: raise ValueError(f"patched content exceeds configured write limit for {raw_path}")
            prepared[canonical] = updated
        written: list[str] = []
        try:
            for raw_path in ordered_paths:
                self._write(raw_path, prepared[raw_path]); written.append(raw_path)
        except BaseException:
            for raw_path in reversed(written):
                try: self._write(raw_path, originals[raw_path])
                except BaseException: pass
            raise
        return {"paths": ordered_paths, "written": True, "changes": len(items)}

    def execute(self, operation: str, path: str = ".", **kwargs: Any) -> dict[str, Any]:
        if operation == "list":
            if os.name == "nt":
                resolved = self.resolve(path, must_exist=True, unrestricted=False)
                entries: list[str] = sorted(p.name for p in resolved.iterdir())
                return {"entries": entries[:self.max_list_entries], "truncated": len(entries) > self.max_list_entries}
            fd = self._open_target(path, directory=True)
            try:
                entries: list[str] = []
                with os.scandir(fd) as scan:
                    for entry in scan:
                        if len(entries) >= self.max_list_entries: return {"entries": sorted(entries), "truncated": True}
                        entries.append(entry.name)
                return {"entries": sorted(entries), "truncated": False}
            finally: os.close(fd)
        if operation == "read":
            content, display = self._read(path); return {"content": content, "path": str(display)}
        if operation == "read_many":
            paths = self._bounded_list(kwargs.get("paths"), "paths")
            return {"items": [{"content": content, "path": str(display)} for content, display in (self._read(str(item)) for item in paths)]}
        if operation == "write": return {"path": self._write(path, str(kwargs["content"])), "written": True}
        if operation == "patch":
            content, _ = self._read(path); old, new = str(kwargs["old"]), str(kwargs["new"])
            if old not in content: raise ValueError("patch text was not found")
            return {"path": self._write(path, content.replace(old, new, 1)), "written": True}
        if operation in {"patch_many", "apply_patch"}: return self._patch_many(kwargs.get("changes"))
        if operation in {"delete", "stat"}:
            if os.name == "nt":
                resolved = self.resolve(path, unrestricted=False)
                info = resolved.lstat()
                if operation == "stat": return {"path": str(resolved), "is_directory": stat.S_ISDIR(info.st_mode), "size": info.st_size, "modified": info.st_mtime}
                if resolved.is_dir(): resolved.rmdir()
                else: resolved.unlink()
                return {"path": str(resolved), "deleted": True}
            parent, name, display = self._open_parent(path)
            try:
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if operation == "stat": return {"path": str(display), "is_directory": stat.S_ISDIR(info.st_mode), "size": info.st_size, "modified": info.st_mtime}
                if stat.S_ISDIR(info.st_mode): os.rmdir(name, dir_fd=parent)
                else: os.unlink(name, dir_fd=parent)
                return {"path": str(display), "deleted": True}
            finally: os.close(parent)
        if operation == "stat_many":
            if os.name == "nt":
                paths = self._bounded_list(kwargs.get("paths"), "paths")
                items = []
                for raw_path in paths:
                    resolved = self.resolve(str(raw_path), unrestricted=False)
                    info = resolved.lstat()
                    items.append({"path": str(resolved), "is_directory": stat.S_ISDIR(info.st_mode), "size": info.st_size, "modified": info.st_mtime})
                return {"items": items}
            paths = self._bounded_list(kwargs.get("paths"), "paths")
            items = []
            for raw_path in paths:
                parent, name, display = self._open_parent(str(raw_path))
                try:
                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    items.append({"path": str(display), "is_directory": stat.S_ISDIR(info.st_mode), "size": info.st_size, "modified": info.st_mtime})
                finally: os.close(parent)
            return {"items": items}
        if operation in {"search", "search_text"}:
            if os.name == "nt":
                include = [str(item) for item in (kwargs.get("include") or [])]
                exclude = [str(item) for item in (kwargs.get("exclude") or [])]
                maximum = min(max(int(kwargs.get("max_results") or 100), 1), 1_000)
                return self._search_nt(path, str(kwargs["query"]), detailed=operation == "search_text", include=include, exclude=exclude, max_results=maximum)
            include = [str(item) for item in (kwargs.get("include") or [])]
            exclude = [str(item) for item in (kwargs.get("exclude") or [])]
            maximum = min(max(int(kwargs.get("max_results") or 100), 1), 1_000)
            return self._search(path, str(kwargs["query"]), detailed=operation == "search_text", include=include, exclude=exclude, max_results=maximum)
        raise ValueError("unsupported filesystem operation")

    def _search_nt(self, path: str, needle: str, *, detailed: bool, include: list[str], exclude: list[str], max_results: int) -> dict[str, Any]:
        # ponytail: Windows-compatible search using pathlib instead of dir_fd.
        if not needle: raise ValueError("query must not be empty")
        base = self.resolve(path, must_exist=True, unrestricted=False)
        matches: list[Any] = []
        inspected = 0
        directories = 0
        truncated = False
        for item in base.rglob("*"):
            if inspected >= self.max_search_files or len(matches) >= max_results:
                truncated = True; break
            if self._is_protected(item): continue
            relative = item.relative_to(base)
            if item.is_dir():
                directories += 1
                if directories > self.max_search_directories: truncated = True; break
                continue
            if item.is_file():
                inspected += 1
                if item.stat().st_size > self.max_read_bytes or not self._matches(relative, include, exclude): continue
                try: text = item.read_text(encoding="utf-8", errors="ignore")
                except OSError: continue
                if detailed:
                    for line_number, line in enumerate(text.splitlines(), 1):
                        if needle in line:
                            matches.append({"path": str(item), "relative_path": relative.as_posix(), "line": line_number, "text": line[:500]})
                            if len(matches) >= max_results: truncated = True; break
                elif needle in text:
                    matches.append(str(item))
        return {"matches": matches, "truncated": truncated, "inspected_files": inspected, "inspected_directories": directories}
