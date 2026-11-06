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

    def test_ponytail_retains_upstream_license(self):
        text = (ROOT / "skills/ponytail/SKILL.md").read_text(encoding="utf-8")
        license_text = (ROOT / "skills/ponytail/LICENSE").read_text(encoding="utf-8")
        self.assertIn("name: ponytail", text)
        self.assertIn("MIT", text)
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026", license_text)
        self.assertIn("DietrichGebert", (ROOT / "skills/README.md").read_text(encoding="utf-8"))

    def test_portable_route_and_recovery_skills(self):
        for name in ("tool-routing", "connection-recovery", "agent-desktop-portable"):
            with self.subTest(name=name):
                text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\nname: " + name))
                self.assertIn("Remote Desktop Commander" if name != "agent-desktop-portable" else "agent-desktop", text)
        routing = (ROOT / "skills/tool-routing/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("median", routing)
        self.assertIn("task type", routing)
        self.assertIn("post-state", routing)
        recovery = (ROOT / "skills/connection-recovery/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("PLAYBOOK.md", recovery)
        self.assertIn("explicit approval", recovery)
        self.assertIn("tools/list", recovery)
        self.assertTrue((ROOT / "skills/connection-recovery/PLAYBOOK.md").is_file())

    def test_repo_instructions_reference_both(self):
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("skills/development-loop/SKILL.md", text)
        self.assertIn("skills/ponytail/SKILL.md", text)
        self.assertIn("never widen allowed filesystem roots", text)


if __name__ == "__main__":
    unittest.main()
