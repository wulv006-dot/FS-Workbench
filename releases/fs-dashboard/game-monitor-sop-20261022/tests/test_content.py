import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import verify

class Content(unittest.TestCase):
    def test_frozen_baseline_and_content_contract(self):
        report = Path(__file__).resolve().parents[1]/"tools/verify-report.json"
        self.assertFalse(report.exists())
        self.assertEqual(verify.main(), 0)
        self.assertGreaterEqual(len(verify.results), 71)
        self.assertFalse(report.exists())
