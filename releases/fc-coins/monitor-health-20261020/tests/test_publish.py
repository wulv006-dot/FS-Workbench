import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("health_publish", Path(__file__).resolve().parents[1] / "publish.py")
publish = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish)


class PublishChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "source").mkdir()
        self.target = self.root / "active.py"
        self.target.write_text("old = True\n")
        (self.root / "source/hooks.py").write_text("new = True\n")
        self.base = self.root / "base.py"
        self.base.write_text("base = True\n")
        self.patches = [
            patch.object(publish, "STAGE", self.root),
            patch.object(publish, "TARGET", self.target),
            patch.object(publish, "BASE", self.base),
            patch.object(publish, "BEFORE", publish.digest(self.target)),
            patch.object(publish, "AFTER", publish.digest(self.root / "source/hooks.py")),
            patch.object(publish, "BASE_SHA", publish.digest(self.base)),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_exact_baseline(self):
        publish.verify()

    def test_target_drift(self):
        self.target.write_text("other = True")
        with self.assertRaises(ValueError):
            publish.verify()

    def test_candidate_drift(self):
        (self.root / "source/hooks.py").write_text("other = True")
        with self.assertRaises(ValueError):
            publish.verify()

    def test_publisher_drift(self):
        self.base.write_text("other = True")
        with self.assertRaises(ValueError):
            publish.verify()

    def test_target_symlink(self):
        self.target.unlink()
        self.target.symlink_to(self.base)
        with self.assertRaises(ValueError):
            publish.verify()

    def test_root_required(self):
        with patch.object(publish.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(ValueError, "root_required"):
                publish.publish()


if __name__ == "__main__":
    unittest.main()
