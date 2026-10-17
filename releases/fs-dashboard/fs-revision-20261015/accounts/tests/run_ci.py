"""Portable standard-library checks; browser assertions are verified separately."""
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
suite = unittest.TestSuite()
for name in ('test_accounts', 'test_http', 'test_publisher'):
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
assert suite.countTestCases() == 29
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
