import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pr_fast


class KnowledgeSourceHashesTest(unittest.TestCase):
    def test_pr_source_edit_requires_each_effective_hash_to_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Tester", "-c", "user.email=test@example.test",
                 "commit", "-qm", "base", "--allow-empty"], cwd=root, check=True,
            )
            source_path = "docs/contract.md"
            source = root / source_path
            source.parent.mkdir()
            source.write_bytes(b"hello world\r\n")
            expected = "a948904f2f0f479b8f8197694b30184b0d2ed1c1cd2a1ec0fb85d299a192a447"
            index = root / "knowledge/index.json"
            index.parent.mkdir()
            entries = [
                {"id": identity, "layer": layer, "status": status,
                 "source": {"path": source_path, "sha256": "0" * 64, "hash_basis": "utf8_lf"}}
                for identity, layer, status in (
                    ("fc.pricing.constraints", "current", "effective"),
                    ("fc.pricing.v3", "current", "effective"),
                    ("archived", "archive", "superseded"),
                )
            ]
            index.write_text(json.dumps({"entries": entries}), encoding="utf-8")
            paths = root / "paths"
            paths.write_bytes(source_path.encode() + b"\0")

            with patch.object(pr_fast, "ROOT", root), patch.object(pr_fast, "selfcheck"), \
                    patch.object(sys, "argv", ["pr_fast.py", str(paths), "HEAD", "HEAD"]), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(RuntimeError) as failure:
                    pr_fast.main()
                message = str(failure.exception)
                for identity in ("fc.pricing.constraints", "fc.pricing.v3"):
                    self.assertIn(identity, message)
                self.assertIn(expected, message)
                self.assertIn("CLOSEOUT.md", message)
                self.assertNotIn("archived", message)

                for row in entries[:2]:
                    row["source"]["sha256"] = expected
                index.write_text(json.dumps({"entries": entries}), encoding="utf-8")
                pr_fast.main()
