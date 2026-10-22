import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import verify

class Content(unittest.TestCase):
    def test_frozen_baseline_and_content_contract(self):
        self.assertEqual(verify.main(), 0)
        self.assertGreaterEqual(len(verify.results), 73)
