"""Entry for the repository's isolated, network/process-blocked affected-test runner."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'source'),str(ROOT/'tests'),str(ROOT/'test_support')]

def load_tests(loader,tests,pattern):
    return unittest.TestSuite(loader.loadTestsFromName(name) for name in
        ('test_deep','test_integration','test_ai_advisor','test_boss_insights','test_fc_daily','test_release_deep'))
