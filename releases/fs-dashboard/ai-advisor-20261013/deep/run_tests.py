"""Run candidate modules first, including all unchanged shared consumer tests."""
from pathlib import Path
import ast
import sys
import unittest
ROOT=Path(__file__).resolve().parent
BASE=ROOT/'test_support'
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'tests'),str(BASE)]
for p in (ROOT/'source').glob('*.py'):
    ast.parse(p.read_text('utf-8'),filename=str(p),feature_version=(3,9))
suite=unittest.defaultTestLoader.loadTestsFromNames(['test_deep','test_integration','test_ai_advisor','test_boss_insights','test_fc_daily','test_release_deep'])
result=unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(not result.wasSuccessful())
