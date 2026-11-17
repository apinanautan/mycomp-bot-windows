"""The two portable coding skills remain bundled and usable without private tools."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BundledSkillTests(unittest.TestCase):
    def test_development_loop_is_actionable_and_safe(self):
        text = (ROOT / "skills/development-loop/SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: development-loop\n"))
        for term in ("AGENTS.md", "git status", "source of truth", "restart",
                     "regression check", "STATE.md", "complete", "iterate",
                     "blocked", "explicit permission", "secrets"):
            with self.subTest(term=term):
                self.assertIn(term, text)

    def test_only_current_skills_are_bundled(self):
        names = sorted(item.name for item in (ROOT / "skills").iterdir() if item.is_dir())
        self.assertEqual(names, ["chat-handoff", "codex-luna", "development-loop", "fast-batch", "mycomp-operator", "tidmunz-studio-ai-operator"])

    def test_fast_batch_teaches_fewer_calls(self):
        text = (ROOT / "skills/fast-batch/SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: fast-batch\n"))
        for term in ("batch_read", "batch_execute", "steps", "post-state"):
            with self.subTest(term=term):
                self.assertIn(term, text)

    def test_operator_skill_covers_target_channels_and_recovery(self):
        doc = (ROOT / "skills/mycomp-operator/SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(doc.startswith("---\nname: mycomp-operator\n"))
        for word in ("machine A", "machine B", "Tidmunz Studio", "Tailscale", "Tunnel",
                     "Remote Desktop Commander", "tools/list", "blocked_permission",
                     "PLAYBOOK.md", "independent work", "Skill set version"):
            with self.subTest(word=word):
                self.assertIn(word, doc)
        self.assertTrue((ROOT / "skills/mycomp-operator/PLAYBOOK.md").is_file())

    def test_tidmunz_bundle_is_complete(self):
        import json
        base = ROOT / "skills/tidmunz-studio-ai-operator"
        catalog = json.loads((base / "catalog.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(catalog["skills"]), 10)
        for skill in catalog["skills"]:
            self.assertTrue((base / skill["path"].removeprefix("skills/")).is_file(), skill["name"])

    def test_codex_luna_checks_login_and_stays_sandboxed(self):
        text = (ROOT / "skills/codex-luna/SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---" + chr(10) + "name: codex-luna" + chr(10)))
        for term in ("codex login status", "gpt-6-luna", "read-only", "at most 3", "Account match", "codex logout"):
            self.assertIn(term, text)
        self.assertIn("Never use `--dangerously-bypass-approvals-and-sandbox`", text)

    def test_chat_handoff_saves_and_resumes(self):
        text = (ROOT / "skills/chat-handoff/SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---" + chr(10) + "name: chat-handoff" + chr(10)))
        for term in ("HANDOFF.md", "Documents", "Status: open", "Next step", "ต่องาน", "Never write tokens", "ready-to-copy summary", "ต่องาน —"):
            self.assertIn(term, text)

    def test_repo_instructions_reference_current_skills(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for name in ("mycomp-operator", "fast-batch", "development-loop"):
            self.assertIn(f"skills/{name}/SKILL.md", text)
        self.assertIn("never widen allowed filesystem roots", text)

if __name__ == "__main__":
    unittest.main()
