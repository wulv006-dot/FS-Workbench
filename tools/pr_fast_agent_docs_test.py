from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pr_fast
import sync_agent_skills


class AgentDocsChecks(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.write("CLAUDE.md", b"See AGENTS.md.\n")
        self.write("docs/memory/MEMORY.md", b"# Memory\n")

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def agents_md(self, core=b"# Project\n", size=None):
        data = core + "<!-- core-rules-end -->\n\n## 场景索引\n".encode("utf-8")
        return data if size is None else data.ljust(size, b"x")

    def test_full_limit_and_warning(self):
        for size, warned in ((12_288, False), (12_289, True), (16_384, True)):
            with self.subTest(size=size), redirect_stderr(StringIO()) as stderr:
                self.write("AGENTS.md", self.agents_md(size=size))
                pr_fast.check_agents_md_size(self.root)
                self.assertEqual("WARNING: AGENTS.md" in stderr.getvalue(), warned)

        self.write("AGENTS.md", self.agents_md(size=16_385))
        with self.assertRaisesRegex(RuntimeError, r"AGENTS\.md.*16385.*16384.*docs/agents/"):
            pr_fast.check_agents_md_size(self.root)

    def test_core_limit_counts_utf8_bytes_after_lf_normalization(self):
        core = "中".encode("utf-8") * 2_047 + b"\n\n\n"
        self.assertEqual(len(core), 6_144)
        self.write("AGENTS.md", self.agents_md(core).replace(b"\n", b"\r\n"))
        pr_fast.check_agents_md_size(self.root)

        self.write("AGENTS.md", self.agents_md(b"x" + core).replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(RuntimeError, r"AGENTS\.md core.*6145.*6144"):
            pr_fast.check_agents_md_size(self.root)

    def test_core_marker_is_required_and_must_precede_the_index(self):
        for content in (b"No marker", self.agents_md(b"<!-- core-rules-end -->\n"),
                        self.agents_md().replace(b"\n\n## ", b"\nOther content\n\n## ")):
            with self.subTest(content=content):
                self.write("AGENTS.md", content)
                with self.assertRaisesRegex(RuntimeError, "core-rules-end"):
                    pr_fast.check_agents_md_size(self.root)

    def test_agents_md_is_required(self):
        with self.assertRaisesRegex(RuntimeError, r"AGENTS\.md.*missing"):
            pr_fast.check_agents_md_size(self.root)

    def test_bridge_and_memory_index_limits(self):
        self.write("AGENTS.md", self.agents_md())
        for name, limit in (("CLAUDE.md", 512), ("docs/memory/MEMORY.md", 6144)):
            with self.subTest(name=name):
                path = self.write(name, b"x" * limit)
                pr_fast.check_agent_docs(self.root)
                with self.assertRaisesRegex(RuntimeError, rf"{name}.*{limit + 1}.*{limit}"):
                    self.write(name, b"x" * (limit + 1))
                    pr_fast.check_agent_docs(self.root)
                path.write_bytes(b"x" * limit)

    def test_rejects_unregistered_rules_and_allows_root_bridge(self):
        pr_fast.check_client_rules(self.root)
        self.write(".claude/rules/note.md", b"rule\n")
        self.write(".codex/rules", b"rule\n")
        self.write("module/CLAUDE.md", b"separate rule\n")
        with self.assertRaisesRegex(RuntimeError, r"\.claude/rules.*\.codex/rules.*module/CLAUDE\.md"):
            pr_fast.check_client_rules(self.root)

    def test_matching_skill_trees_accept_local_and_root_links(self):
        self.write("docs/guide.md", b"# Project guide\n")
        for directory in (".agents/skills", ".claude/skills"):
            self.write(f"{directory}/example/SKILL.md",
                       b"[Local](references/guide.md)\n[Project](docs/guide.md#project-guide)\n")
            self.write(f"{directory}/example/references/guide.md", b"# Local guide\n")
        sync_agent_skills.sync(self.root)

    def test_check_is_read_only_and_apply_adds_updates_and_deletes(self):
        source = self.write(".agents/skills/example/SKILL.md", b"# Source\r\n")
        mirror = self.write(".claude/skills/example/SKILL.md", b"# Old\r\n")
        added = ".claude/skills/example/references/new.md"
        self.write(".agents/skills/example/references/new.md", b"# Addition\r\n")
        stale = self.write(".claude/skills/retired/SKILL.md", b"# Retired\n")

        with self.assertRaisesRegex(ValueError, r"sync_agent_skills\.py --apply") as error:
            sync_agent_skills.sync(self.root)
        for reason in ("missing from .claude/skills", "extra in .claude/skills", "content differs"):
            self.assertIn(reason, str(error.exception))
        self.assertEqual(mirror.read_bytes(), b"# Old\r\n")
        self.assertFalse((self.root / added).exists())
        self.assertTrue(stale.exists())

        sync_agent_skills.sync(self.root, apply=True)
        self.assertEqual(mirror.read_bytes(), b"# Source\n")
        self.assertEqual((self.root / added).read_bytes(), b"# Addition\n")
        self.assertFalse(stale.parent.exists())
        self.assertEqual(source.read_bytes(), b"# Source\r\n")
        sync_agent_skills.sync(self.root)

    def test_rejects_missing_and_parent_relative_links_before_apply(self):
        self.write("docs/guide.md", b"# Project guide\n")
        original = self.write(".claude/skills/example/SKILL.md", b"# Existing mirror\n")
        for target in ("docs/missing.md", "../../../docs/guide.md"):
            with self.subTest(target=target):
                self.write(".agents/skills/example/SKILL.md", f"[Guide]({target})\n".encode())
                with self.assertRaisesRegex(ValueError, "skill-link:"):
                    sync_agent_skills.sync(self.root, apply=True)
                self.assertEqual(original.read_bytes(), b"# Existing mirror\n")


if __name__ == "__main__":
    unittest.main()
