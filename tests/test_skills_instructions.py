import tempfile
import unittest
from pathlib import Path

from mycomp_bot_engine.server import skills_instructions


class SkillsInstructionsTests(unittest.TestCase):
    def test_real_install_lists_version_and_skills(self):
        text = skills_instructions()
        version = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
        self.assertIn(f"Skill set version: {version}", text)
        self.assertIn(f"/tree/v{version}/skills", text)
        for name in ("codex-luna", "fast-batch", "mycomp-operator", "tidmunz-studio-ai-operator"):
            self.assertIn(name, text)
        self.assertIn("without asking", text)

    def test_missing_files_fall_back_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertNotIn("Skill set version", skills_instructions(Path(directory)))


if __name__ == "__main__":
    unittest.main()
