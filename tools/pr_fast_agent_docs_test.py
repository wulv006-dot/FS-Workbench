from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pr_fast


class AgentDocsChecks(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.agents = self.root / ".agents/skills"
        self.claude = self.root / ".claude/skills"
        self.skill = "example/SKILL.md"
        for skills in (self.agents, self.claude):
            self.write(skills / self.skill, b"# Example\n")

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def test_agents_md_limit_counts_utf8_bytes(self):
        path = self.root / "AGENTS.md"
        at_limit = "中".encode("utf-8") * 6_666 + b"\n\n"
        self.write(path, at_limit)
        pr_fast.check_agents_md_size(self.root)

        self.write(path, at_limit + b"x")
        with self.assertRaisesRegex(RuntimeError, r"AGENTS\.md.*20001.*20000.*docs/agents/"):
            pr_fast.check_agents_md_size(self.root)

    def test_agents_md_is_required(self):
        with self.assertRaisesRegex(RuntimeError, r"AGENTS\.md.*missing"):
            pr_fast.check_agents_md_size(self.root)

    def test_matching_trees_include_supporting_files(self):
        for skills in (self.agents, self.claude):
            self.write(skills / "example/references/guide.md", b"# Guide\n")
        pr_fast.check_skill_parity(self.root)

    def test_skill_sets_must_match_in_both_directions(self):
        for present, missing in ((self.agents, ".claude"), (self.claude, ".agents")):
            with self.subTest(missing=missing):
                extra = present / "extra/SKILL.md"
                self.write(extra, b"# Extra\n")
                with self.assertRaisesRegex(RuntimeError, rf"missing from {missing}/skills: extra/SKILL\.md"):
                    pr_fast.check_skill_parity(self.root)
                extra.unlink()

    def test_matching_skill_with_different_content_fails(self):
        self.write(self.claude / self.skill, b"# Different\n")
        with self.assertRaisesRegex(RuntimeError, r"content differs: example/SKILL\.md"):
            pr_fast.check_skill_parity(self.root)

    def test_missing_supporting_file_fails(self):
        self.write(self.claude / "example/references/guide.md", b"# Guide\n")
        with self.assertRaisesRegex(RuntimeError, r"missing from \.agents/skills: example/references/guide\.md"):
            pr_fast.check_skill_parity(self.root)

    def test_different_supporting_file_fails(self):
        guide = "example/references/guide.md"
        self.write(self.agents / guide, b"# First\n")
        self.write(self.claude / guide, b"# Second\n")
        with self.assertRaisesRegex(RuntimeError, r"content differs: example/references/guide\.md"):
            pr_fast.check_skill_parity(self.root)
