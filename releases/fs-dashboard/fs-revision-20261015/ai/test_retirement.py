"""Retirement must not touch storage, credentials, networking or Hermes accounting."""
import ast
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'candidate'))
sys.path.append(str(ROOT / 'baseline'))
import fc_daily
import fc_daily_model
import ai_advisor_model
import ai_advisor


class RetirementTests(unittest.TestCase):
    def test_legacy_advisor_worker_and_all_submission_paths_are_retired(self):
        service = object.__new__(ai_advisor.Advisor)
        service.authorizer = lambda user: user == 'admin'
        self.assertIsNone(service.start())
        self.assertFalse(service.run_one())
        self.assertEqual(service.enqueue('admin', 'any-request', 'report', {})[0], 410)
        for call in (service.post, service.post_boss):
            self.assertEqual(call({}, '', {})[0], 401)
            self.assertEqual(call({}, 'reader', {})[0], 403)
            self.assertEqual(call({}, 'admin', {})[0], 410)

    def test_no_background_or_manual_generation(self):
        service = object.__new__(fc_daily.DailyReports)
        self.assertIsNone(service.start())
        self.assertIsNone(service.tick())
        self.assertFalse(service.run_one())
        self.assertEqual(service.enqueue('2026-10-14', 'new-request')['state'], 'retired')

    def test_provider_never_reads_key_or_opens_network(self):
        with patch('pathlib.Path.read_text', side_effect=AssertionError('credential read')), patch('urllib.request.build_opener', side_effect=AssertionError('network')):
            self.assertFalse(fc_daily_model.configured())
            self.assertEqual(fc_daily_model.explain({})['status'], 'retired')
            self.assertEqual(ai_advisor_model.request_model([], {}, None)['status'], 'retired')

    def test_shared_ledger_and_source_semantics_unchanged(self):
        before = ast.parse((ROOT / 'baseline/fc_daily.py').read_text('utf-8'))
        after = ast.parse((ROOT / 'candidate/fc_daily.py').read_text('utf-8'))
        def functions(tree):
            return {n.name: ast.dump(n, include_attributes=False) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        a, b = functions(before), functions(after)
        for name in ('db', 'bounded_model', '_send_model', 'provider_slot', 'model_daily_limit', 'latest', 'source', 'build_report', 'admin'):
            self.assertEqual(a[name], b[name], name)


if __name__ == '__main__':
    unittest.main()
