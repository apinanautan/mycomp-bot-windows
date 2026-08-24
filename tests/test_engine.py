import tempfile
import unittest
import base64
import hashlib
import os
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from mycomp_bot_engine.capabilities import CapabilityRegistry
from mycomp_bot_engine.config import Settings
from mycomp_bot_engine.database import Database
from mycomp_bot_engine.filesystem import Filesystem
from mycomp_bot_engine.jobs import Shell
from mycomp_bot_engine.oauth import OAuthService
from mycomp_bot_engine.runtime import RuntimeController
from mycomp_bot_engine.schema import TOOL_NAMES

try:
    from mycomp_bot_engine.server import build_server
except ModuleNotFoundError:
    build_server = None


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "root"; self.root.mkdir()
        self.db = Database(Path(self.temp.name) / "state")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_exact_stable_tool_surface(self):
        self.assertEqual(len(TOOL_NAMES), 8)
        self.assertEqual(set(TOOL_NAMES), {"api", "shell", "dom_cdp", "applescript", "accessibility", "keyboard", "mouse", "vision"})

    def test_settings_reject_invalid_auth_mode(self):
        with self.assertRaises(ValueError):
            Settings(host="127.0.0.1", port=8645, allowed_roots=(self.root,), allow_shell=False, allowed_executables=(), data_dir=Path(self.temp.name) / "state-invalid-auth", capability_dir=Path(self.temp.name) / "caps-invalid-auth", redirect_uris=frozenset(), owner_consent_token=None, auth_mode="invalid")

    def test_settings_strip_whitespace_from_oauth_redirect_uris(self):
        with patch.dict(os.environ, {
            "MYCOMP_OAUTH_REDIRECT_URIS": (
                "https://chatgpt.com/connector/oauth/one, "
                "https://chatgpt.com/connector/two"
            ),
        }):
            settings = Settings.from_env()
        self.assertEqual(settings.redirect_uris, frozenset({
            "https://chatgpt.com/connector/oauth/one",
            "https://chatgpt.com/connector/two",
        }))

    @unittest.skipIf(build_server is None, "MCP SDK is not installed in this environment")
    def test_server_registers_exact_stable_tool_surface(self):
        import asyncio
        settings = Settings(host="127.0.0.1", port=8645, allowed_roots=(self.root,), allow_shell=False, allowed_executables=(), data_dir=Path(self.temp.name) / "server-state", capability_dir=Path(self.temp.name) / "server-caps", redirect_uris=frozenset(), owner_consent_token=None)
        server = build_server(settings)
        try:
            tools = asyncio.run(server.list_tools())
            self.assertEqual({tool.name for tool in tools}, set(TOOL_NAMES))
        finally:
            server._mycomp_resources.close()

    @unittest.skipIf(build_server is None, "MCP SDK is not installed in this environment")
    def test_server_protects_control_plane_when_an_allowed_root_contains_it(self):
        data_dir = Path(self.temp.name) / "control" / "state"
        root = data_dir.parents[1]
        settings = Settings(host="127.0.0.1", port=8645, allowed_roots=(root,), allow_shell=False, allowed_executables=(), data_dir=data_dir, capability_dir=data_dir / "capabilities", redirect_uris=frozenset(), owner_consent_token=None)
        server = build_server(settings)
        try:
            files = server._mycomp_resources.files
            files.execute("write", "ordinary.txt", content="safe")
            self.assertEqual(files.execute("read", "ordinary.txt")["content"], "safe")
            with self.assertRaises(PermissionError): files.execute("write", str(data_dir / "state.sqlite3"), content="tamper")
            with self.assertRaises(PermissionError): files.execute("read", str(data_dir / "state.sqlite3"))
            with self.assertRaises(PermissionError): files.resolve(str(data_dir), must_exist=True)
            (data_dir / "secret.txt").write_text("secret")
            self.assertEqual(files.execute("search", ".", query="secret")["matches"], [])
        finally:
            server._mycomp_resources.close()

    def test_capability_directory_requires_protection_when_it_is_below_an_allowed_root(self):
        directory = self.root / "capabilities"
        with self.assertRaises(ValueError): CapabilityRegistry(directory, self.db, (self.root,))
        registry = CapabilityRegistry(directory, self.db, (self.root,), protected_paths=(directory,))
        self.assertEqual(registry.search(), [])

    @unittest.skipIf(build_server is None, "MCP SDK is not installed in this environment")
    def test_server_allows_normal_root_outside_control_plane(self):
        settings = Settings(host="127.0.0.1", port=8645, allowed_roots=(self.root,), allow_shell=False, allowed_executables=(), data_dir=Path(self.temp.name) / "control", capability_dir=Path(self.temp.name) / "control" / "capabilities", redirect_uris=frozenset(), owner_consent_token=None)
        server = build_server(settings)
        server._mycomp_resources.close()

    @unittest.skipIf(build_server is None, "MCP SDK is not installed in this environment")
    def test_server_protects_separate_config_dir_inside_an_allowed_root(self):
        settings = Settings(
            host="127.0.0.1", port=8645, allowed_roots=(self.root,), allow_shell=False,
            allowed_executables=(), data_dir=Path(self.temp.name) / "state",
            capability_dir=Path(self.temp.name) / "capabilities",
            redirect_uris=frozenset(), owner_consent_token=None, config_dir=self.root,
        )
        server = build_server(settings)
        try:
            with self.assertRaises(PermissionError): server._mycomp_resources.files.execute("write", str(self.root / ".env"), content="tamper")
        finally:
            server._mycomp_resources.close()

    def test_filesystem_operations_and_root_boundary(self):
        fs = Filesystem((self.root.resolve(),))
        fs.execute("write", "a.txt", content="one")
        self.assertEqual(fs.execute("read", "a.txt")["content"], "one")
        fs.execute("patch", "a.txt", old="one", new="two")
        self.assertEqual(fs.execute("search", ".", query="two")["matches"], [str((self.root / "a.txt").resolve())])
        self.assertEqual(fs.execute("stat", "a.txt")["size"], 3)
        fs.execute("delete", "a.txt")
        with self.assertRaises(PermissionError): fs.execute("read", "../outside")

    def test_filesystem_unrestricted_resolve_allows_outside_roots_but_protects_control_plane(self):
        control = Path(self.temp.name) / "control"
        control.mkdir()
        outside = Path(self.temp.name) / "outside-dir"
        outside.mkdir()
        fs = Filesystem((self.root.resolve(),), protected_paths=(control,))
        with self.assertRaises(PermissionError):
            fs.resolve(str(outside), must_exist=True)
        resolved = fs.resolve(str(outside), must_exist=True, unrestricted=True)
        self.assertEqual(resolved, outside.resolve())
        with self.assertRaises(PermissionError):
            fs.resolve(str(control), must_exist=True, unrestricted=True)

    def test_filesystem_rejects_temp_symlink_and_oversized_read(self):
        fs = Filesystem((self.root.resolve(),), max_read_bytes=4)
        outside = Path(self.temp.name) / "outside"; outside.write_text("safe")
        (self.root / ".victim.txt.tmp").symlink_to(outside)
        fs.execute("write", "victim.txt", content="ok")
        self.assertEqual(outside.read_text(), "safe")
        (self.root / "large.txt").write_text("12345")
        with self.assertRaises(ValueError): fs.execute("read", "large.txt")

    def test_filesystem_write_list_and_search_limits(self):
        fs = Filesystem((self.root.resolve(),), max_read_bytes=32, max_list_entries=2, max_write_bytes=3, max_search_files=1, max_search_directories=1, max_search_depth=1)
        with self.assertRaises(ValueError): fs.execute("write", "large", content="four")
        for name in ("a", "b", "c"): (self.root / name).write_text("needle")
        self.assertTrue(fs.execute("list", ".")["truncated"])
        self.assertTrue(fs.execute("search", ".", query="needle")["truncated"])

    def test_filesystem_batch_search_and_atomic_patch(self):
        fs = Filesystem((self.root.resolve(),))
        fs.execute("write", "src/a.py", content="first needle\nsecond\n")
        fs.execute("write", "src/b.py", content="other needle\n")
        read = fs.execute("read_many", paths=["src/a.py", "src/b.py"])
        self.assertEqual([Path(item["path"]).name for item in read["items"]], ["a.py", "b.py"])
        stats = fs.execute("stat_many", paths=["src/a.py", "src/b.py"])
        self.assertEqual(len(stats["items"]), 2)
        found = fs.execute("search_text", ".", query="needle", include=["src/*.py"], exclude=["src/b.py"])
        self.assertEqual([(item["relative_path"], item["line"]) for item in found["matches"]], [("src/a.py", 1)])
        changed = fs.execute("apply_patch", changes=[
            {"path": "src/a.py", "old": "first", "new": "updated"},
            {"path": "src/b.py", "old": "other", "new": "changed"},
        ])
        self.assertEqual(changed["changes"], 2)
        self.assertIn("updated", fs.execute("read", "src/a.py")["content"])
        before = fs.execute("read", "src/a.py")["content"]
        with self.assertRaises(ValueError):
            fs.execute("patch_many", changes=[
                {"path": "src/a.py", "old": "updated", "new": "partial"},
                {"path": "src/b.py", "old": "missing", "new": "never"},
            ])
        self.assertEqual(fs.execute("read", "src/a.py")["content"], before)

    @unittest.skipIf(build_server is None, "MCP SDK is not installed in this environment")
    def test_server_operation_schemas_are_enumerated(self):
        import asyncio
        settings = Settings(host="127.0.0.1", port=8645, allowed_roots=(self.root,), allow_shell=False, allowed_executables=(), data_dir=Path(self.temp.name) / "schema-state", capability_dir=Path(self.temp.name) / "schema-caps", redirect_uris=frozenset(), owner_consent_token=None)
        server = build_server(settings)
        try:
            tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
            self.assertIn("GET", tools["api"].inputSchema["properties"]["method"]["enum"])
            self.assertIn("approve", tools["shell"].inputSchema["properties"]["operation"]["enum"])
            self.assertIn("query", tools["dom_cdp"].inputSchema["properties"]["action"]["anyOf"][0]["enum"])
            self.assertIn("AppleScript", tools["applescript"].inputSchema["properties"]["language"]["enum"])
            self.assertIn("inspect_elements", tools["accessibility"].inputSchema["properties"]["action"]["enum"])
            self.assertIn("hotkey", tools["keyboard"].inputSchema["properties"]["action"]["enum"])
            self.assertIn("drag", tools["mouse"].inputSchema["properties"]["action"]["enum"])
            self.assertIn("ocr", tools["vision"].inputSchema["properties"]["action"]["enum"])
            self.assertNotIn("capability_execute", tools)
        finally:
            server._mycomp_resources.close()

    @unittest.skipIf(build_server is None, "MCP SDK is not installed in this environment")
    def test_public_adapters_do_not_fallback_between_tools(self):
        settings = Settings(host="127.0.0.1", port=8645, allowed_roots=(self.root,), allow_shell=False, allowed_executables=(), data_dir=Path(self.temp.name) / "adapter-state", capability_dir=Path(self.temp.name) / "adapter-caps", redirect_uris=frozenset(), owner_consent_token=None, auth_mode="none", permission_level="full")
        server = build_server(settings)
        try:
            capability_execute = Mock(return_value={"ok": False, "error": "AX element was not found"})
            server._mycomp_resources.capabilities.execute = capability_execute
            accessibility = server._tool_manager._tools["accessibility"].fn
            failed = accessibility("click", {"selector": {"role": "AXButton", "title": "Missing"}})
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["error"]["backend"], "accessibility")
            capability_execute.assert_called_once()
            self.assertEqual(capability_execute.call_args.args[0], "macos_ui")
            self.assertEqual(capability_execute.call_args.args[1]["allow_ocr_fallback"], False)
            self.assertEqual(capability_execute.call_args.args[1]["allow_coordinate_fallback"], False)

            capability_execute.reset_mock(return_value=True)
            capability_execute.return_value = {"ok": True, "result": {"items": [{"text": "Export", "confidence": 0.95, "frame": {"x": 10, "y": 20, "width": 30, "height": 40}, "center": {"x": 25, "y": 40}}], "screen_revision": "sha256:test"}}
            vision = server._tool_manager._tools["vision"].fn
            observed = vision("ocr", text="Export", min_confidence=0.8)
            self.assertEqual(observed["status"], "completed")
            self.assertEqual(observed["results"][0]["observation"]["items"][0]["center"], {"x": 25, "y": 40})
            capability_execute.assert_called_once_with("macos_ui", {"timeout_seconds": 30, "action": "ocr"})

            capability_execute.reset_mock(return_value=True)
            capability_execute.return_value = {"ok": True, "result": {"moved": True, "point": {"x": 7, "y": 9}}}
            mouse = server._tool_manager._tools["mouse"].fn
            moved = mouse("move", x=7, y=9)
            self.assertEqual(moved["status"], "completed")
            capability_execute.assert_called_once_with("macos_ui", {"timeout_seconds": 30, "x": 7, "y": 9, "action": "mouse_move"})
        finally:
            server._mycomp_resources.close()

    @unittest.skipIf(build_server is None, "MCP SDK is not installed in this environment")
    def test_api_rejects_private_targets_and_validates_redirect_destinations(self):
        # Elevated keeps SSRF protection; Full Control may reach private/loopback targets.
        settings = Settings(
            host="127.0.0.1", port=8645, allowed_roots=(self.root,), allow_shell=False,
            allowed_executables=(), data_dir=Path(self.temp.name) / "api-state",
            capability_dir=Path(self.temp.name) / "api-caps", redirect_uris=frozenset(),
            owner_consent_token=None, auth_mode="none", permission_level="elevated",
        )
        server = build_server(settings)
        try:
            api = server._tool_manager._tools["api"].fn
            self.assertEqual(api("file:///tmp/nope")["status"], "failed")
            self.assertEqual(api("https://user:pass@example.com/")["status"], "failed")
            with patch("mycomp_bot_engine.server.socket.getaddrinfo", return_value=[(0, 0, 0, "", ("127.0.0.1", 443))]):
                private = api("https://private.example/")
            self.assertEqual(private["error"]["code"], "PERMISSION_DENIED")

            class RedirectResponse:
                code = 302
                status = 302
                reason = "Found"
                headers = {"Location": "http://127.0.0.1/private"}
                def close(self): pass

            opener = Mock()
            opener.open.return_value = RedirectResponse()
            with (
                patch("mycomp_bot_engine.server.socket.getaddrinfo", side_effect=[[(0, 0, 0, "", ("93.184.216.34", 443))], [(0, 0, 0, "", ("127.0.0.1", 80))]]),
                patch("mycomp_bot_engine.server.urllib.request.build_opener", return_value=opener),
            ):
                redirected = api("https://public.example/")
            self.assertEqual(redirected["status"], "failed")
            self.assertEqual(redirected["error"]["code"], "PERMISSION_DENIED")
        finally:
            server._mycomp_resources.close()

    @unittest.skipIf(build_server is None, "MCP SDK is not installed in this environment")
    def test_full_control_api_allows_private_targets(self):
        settings = Settings(
            host="127.0.0.1", port=8645, allowed_roots=(self.root,), allow_shell=False,
            allowed_executables=(), data_dir=Path(self.temp.name) / "api-full-state",
            capability_dir=Path(self.temp.name) / "api-full-caps", redirect_uris=frozenset(),
            owner_consent_token=None, auth_mode="none", permission_level="full",
        )
        server = build_server(settings)
        try:
            api = server._tool_manager._tools["api"].fn

            class HeaderMap(dict):
                def get_content_type(self):
                    return "application/json"

                def get_content_charset(self):
                    return "utf-8"

            class OkResponse:
                code = 200
                status = 200
                reason = "OK"
                headers = HeaderMap({"Content-Type": "application/json"})

                def getcode(self):
                    return 200

                def geturl(self):
                    return "https://private.example/"

                def read(self, _n):
                    return b'{"ok":true}'

                def close(self):
                    pass

            opener = Mock()
            opener.open.return_value = OkResponse()
            with (
                patch("mycomp_bot_engine.server.socket.getaddrinfo", return_value=[(0, 0, 0, "", ("127.0.0.1", 443))]),
                patch("mycomp_bot_engine.server.urllib.request.build_opener", return_value=opener),
            ):
                result = api("https://private.example/")
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(result["results"][0]["status"], 200)
        finally:
            server._mycomp_resources.close()

    def test_settings_reject_relative_shell_path(self):
        with self.assertRaises(ValueError):
            Settings(host="127.0.0.1", port=8645, allowed_roots=(self.root,), allow_shell=False, allowed_executables=(), data_dir=Path(self.temp.name) / "path-state", capability_dir=Path(self.temp.name) / "path-caps", redirect_uris=frozenset(), owner_consent_token=None, shell_path="relative:/usr/bin")

    @unittest.skipUnless(os.name == "nt", "Windows PATHEXT behavior")
    def test_shell_resolves_windows_executable_suffix(self):
        shell = Shell(True, (), self.db, 1000, shell_path=r"C:\Windows\System32")
        self.assertEqual(shell._resolve_executable("cmd", unrestricted=True).name.lower(), "cmd.exe")

    @unittest.skipIf(build_server is None, "MCP SDK is not installed in this environment")
    def test_command_interpreters_are_full_control(self):
        source = Path(__file__).resolve().parents[1] / "src/mycomp_bot_engine/server.py"
        text = source.read_text()
        self.assertIn('executable in {"bash", "zsh", "sh", "dash", "fish", "osascript"}', text)
        self.assertIn('executable.startswith("python")', text)

    def test_shell_requires_opt_in_and_runs_argv(self):
        disabled = Shell(False, (Path("/bin/echo"),), self.db, 1000)
        with self.assertRaises(PermissionError): disabled.run("foreground", ["/bin/echo", "x"], self.root)
        enabled = Shell(True, (Path("/bin/echo").resolve(),), self.db, 1000)
        self.assertEqual(enabled.run("foreground", ["/bin/echo", "ok"], self.root)["stdout"], "ok\n")

    def test_sudo_requires_explicit_owner_approval(self):
        sudo = Path("/usr/bin/sudo").resolve()
        if not sudo.exists():
            self.skipTest("sudo is unavailable")
        shell = Shell(True, (sudo,), self.db, 1000)
        request = shell.run("foreground", [str(sudo), "-n", "/usr/bin/true"], self.root)
        self.assertEqual(request["state"], "approval_required")
        self.assertEqual(request["approval_kind"], "sudo")
        self.assertEqual(request["password_handling"], "user_only")
        stored = shell.control("status", request["job_id"])
        self.assertEqual(stored["state"], "approval_required")
        denied = shell.control("deny", request["job_id"])
        self.assertEqual(denied["state"], "denied")

    def test_non_sudo_command_does_not_require_approval(self):
        shell = Shell(True, (Path("/bin/echo").resolve(),), self.db, 1000)
        result = shell.run("foreground", ["/bin/echo", "ok"], self.root)
        self.assertEqual(result["state"], "finished")

    def test_ui_folder_approval_allow_always_updates_policy(self):
        caps_dir = Path(self.temp.name) / "ui-caps"; caps_dir.mkdir()
        runtime = RuntimeController(Path(self.temp.name) / "ui-state", CapabilityRegistry(caps_dir, self.db))
        request_id = "a" * 32
        request = {
            "id": request_id, "kind": "folder_permission",
            "app_id": "com.example.app", "app_name": "Example",
            "folder": "documents", "dialog": "Example requests Documents"
        }
        RuntimeController._atomic_json(runtime.ui_pending_dir / f"{request_id}.json", request)
        result = runtime.ui_control(f"ui_allow_always:{request_id}")
        self.assertEqual(result["decision"], "allow_always")
        policy = runtime.ui_control("ui_policy")
        self.assertEqual(policy["rules"][-1]["app_id"], "com.example.app")
        self.assertEqual(policy["rules"][-1]["folder"], "documents")
        decision = runtime.ui_decision_dir / f"{request_id}.json"
        self.assertTrue(decision.exists())

    def test_ui_folder_job_control_adapter(self):
        caps_dir = Path(self.temp.name) / "ui-caps-job"; caps_dir.mkdir()
        runtime = RuntimeController(Path(self.temp.name) / "ui-state-job", CapabilityRegistry(caps_dir, self.db))
        request_id = "c" * 32
        request = {
            "id": request_id, "kind": "folder_permission",
            "app_id": "com.example.job", "app_name": "Job Example",
            "folder": "downloads", "dialog": "Job Example requests Downloads"
        }
        RuntimeController._atomic_json(runtime.ui_pending_dir / f"{request_id}.json", request)
        status = runtime.ui_job_control("status", request_id)
        self.assertEqual(status["state"], "approval_required")
        approved = runtime.ui_job_control("approve", request_id)
        self.assertEqual(approved["decision"], "allow_once")
        self.assertEqual(runtime.ui_job_control("status", request_id)["state"], "decision_recorded")

    def test_ui_folder_approval_rejects_unknown_request(self):
        caps_dir = Path(self.temp.name) / "ui-caps-missing"; caps_dir.mkdir()
        runtime = RuntimeController(Path(self.temp.name) / "ui-state-missing", CapabilityRegistry(caps_dir, self.db))
        with self.assertRaises(KeyError):
            runtime.ui_control("ui_allow_once:" + "b" * 32)

    def test_dynamic_capability_does_not_change_schema(self):
        directory = Path(self.temp.name) / "caps"; directory.mkdir()
        (directory / "demo.py").write_text("def execute(payload): return {'echo': payload['x']}\ndef self_test(): return True\n")
        registry = CapabilityRegistry(directory, self.db)
        self.assertEqual(registry.search(), ["demo"])
        self.assertTrue(registry.manage("validate", "demo")["valid"])
        registry.manage("test", "demo")
        registry.manage("activate", "demo")
        self.assertEqual(registry.execute("demo", {"x": "yes"}), {"echo": "yes"})
        registry.manage("deactivate", "demo")
        with self.assertRaises(PermissionError): registry.execute("demo", {"x": "no"})

    def test_capability_executes_immutable_source_after_activation(self):
        directory = Path(self.temp.name) / "caps"; directory.mkdir()
        module = directory / "demo.py"
        module.write_text("def execute(payload): return {'v': 1}\ndef self_test(): return True\n")
        registry = CapabilityRegistry(directory, self.db)
        registry.manage("test", "demo"); registry.manage("activate", "demo")
        module.write_text("def execute(payload): return {'v': 2}\ndef self_test(): return True\n")
        self.assertEqual(registry.execute("demo", {})["v"], 1)

    def test_oauth_pkce_rotation_and_audience(self):
        service = OAuthService(self.db, frozenset({"https://client.example/callback"}), "c" * 32)
        verifier = "verifier"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        code = service.authorize(client_id="mycomp-bot-local-client", redirect_uri="https://client.example/callback", code_challenge=challenge, code_challenge_method="S256", consent_token="c" * 32)
        grant = service.exchange(code=code, redirect_uri="https://client.example/callback", code_verifier=verifier, client_id="mycomp-bot-local-client", audience="https://mycomp.invalid/mcp")
        self.assertTrue(service.validate_access_token(grant.access_token))
        replacement = service.refresh(grant.refresh_token, "https://mycomp.invalid/mcp")
        self.assertTrue(service.validate_access_token(replacement.access_token))
        with self.assertRaises(PermissionError): service.refresh(grant.refresh_token, "https://mycomp.invalid/mcp")

    def test_oauth_code_is_single_use_under_concurrency(self):
        service = OAuthService(self.db, frozenset({"https://client.example/callback"}), "c" * 32)
        verifier = "concurrent-verifier"; challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        code = service.authorize(client_id="mycomp-bot-local-client", redirect_uri="https://client.example/callback", code_challenge=challenge, code_challenge_method="S256", consent_token="c" * 32)
        outcomes = []
        def exchange():
            try: outcomes.append(service.exchange(code=code, redirect_uri="https://client.example/callback", code_verifier=verifier, client_id="mycomp-bot-local-client", audience="https://mycomp.invalid/mcp"))
            except PermissionError: outcomes.append(None)
        threads = [threading.Thread(target=exchange) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(sum(item is not None for item in outcomes), 1)

    def test_capability_requires_true_test_and_rolls_back_immutable_source(self):
        directory = Path(self.temp.name) / "caps"; directory.mkdir(); module = directory / "demo.py"
        module.write_text("def execute(payload): return {'v': 1}\ndef self_test(): return True\n")
        registry = CapabilityRegistry(directory, self.db)
        registry.manage("test", "demo"); registry.manage("activate", "demo")
        module.write_text("def execute(payload): return {'v': 2}\ndef self_test(): return True\n")
        registry.manage("test", "demo"); registry.manage("activate", "demo")
        self.assertEqual(registry.execute("demo", {})["v"], 2)
        registry.manage("rollback", "demo")
        self.assertEqual(registry.execute("demo", {})["v"], 1)
        module.write_text("def execute(payload): return {}\ndef self_test(): return False\n")
        self.assertFalse(registry.manage("test", "demo")["test"])
        with self.assertRaises(PermissionError): registry.manage("activate", "demo")

    def test_capability_validation_never_executes_source_or_overlaps_root(self):
        with self.assertRaises(ValueError): CapabilityRegistry(self.root / "caps", self.db, (self.root,))
        directory = Path(self.temp.name) / "caps"; directory.mkdir()
        marker = Path(self.temp.name) / "executed"
        (directory / "bad.py").write_text(f"open({str(marker)!r}, 'w').write('x')\ndef execute(payload): return {{}}\ndef self_test(): return True\n")
        registry = CapabilityRegistry(directory, self.db)
        self.assertTrue(registry.manage("validate", "bad")["valid"])
        self.assertFalse(marker.exists())

    def test_background_immediate_exit_and_resume(self):
        shell = Shell(True, (Path("/bin/echo").resolve(),), self.db, 128)
        job = shell.run("background", ["/bin/echo", "quick"], self.root)
        import time; time.sleep(.1)
        self.assertEqual(shell.control("status", job["job_id"])["state"], "finished")
        with self.assertRaises(ValueError): shell.control("resume", job["job_id"])

    def test_shell_marks_stale_running_jobs_interrupted(self):
        self.db.save_job("stale", "running", {"argv": ["/bin/echo", "x"], "cwd": str(self.root)})
        Shell(True, (Path("/bin/echo").resolve(),), self.db, 128)
        self.assertEqual(self.db.job("stale")["state"], "interrupted")

    def test_shell_persists_foreground_launch_failure(self):
        shell = Shell(True, (), self.db, 128)
        with self.assertRaises(PermissionError): shell.run("foreground", ["/bin/echo", "x"], self.root)
        row = self.db.connection.execute("SELECT state FROM jobs").fetchone()
        self.assertEqual(row[0], "failed")

if __name__ == "__main__": unittest.main()
