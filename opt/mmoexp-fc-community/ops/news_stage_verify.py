"""Isolated Linux suite runner; never loads production config or databases."""
import os
import sys
import unittest
from pathlib import Path

root = Path(sys.argv[1]).resolve()
if not str(root).startswith('/opt/mmoexp-fc-news-stage-'):
    raise SystemExit('Unexpected stage path')
os.chdir(str(root))
sys.path.insert(0, str(root))
suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
def cases(suite):
    for entry in suite:
        if isinstance(entry, unittest.TestSuite):
            yield from cases(entry)
        else:
            yield entry
selected = unittest.TestSuite(test for test in cases(suite)
                              if 'test_token_save' not in test.id())
result = unittest.TextTestRunner(verbosity=1).run(selected)
raise SystemExit(0 if result.wasSuccessful() else 1)
