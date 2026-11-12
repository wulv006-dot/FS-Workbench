"""Closed history projection must not inherit a covering export's live TTL."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from coins_evidence import es_metadata


class HistoryWindowTests(unittest.TestCase):
    def collect(self, profile='ALL', end='2026-11-11', missing=False, partial=False):
        calls = []
        def archived(query, root):
            calls.append(dict(query))
            # Reproduce the live query's expired 600-second admission.
            if missing or query['end'] >= '2026-11-12':
                return None
            return dict(rows=[{'游戏': 'FC 27', '付款时间': '2026-11-05',
                               '订单号': 'fixture', '产品类型': '货币(Gold)', '折扣金额': '1'}],
                        hashes=['fixture-sha'], captured_at='2026-11-12T07:48:00Z',
                        parse_failures=int(partial), failed_files=0, declared_files=1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query = dict(profile=profile, start='2026-11-01', end='2026-11-12')
            (root / 'manifest.json').write_text(json.dumps(dict(query=query, captured_at='2026-11-12T07:48:00Z')))
            with patch.dict(sys.modules, es_order_structure=SimpleNamespace(archived_dataset=archived)):
                rows, proof = es_metadata('2026-11-05', end, root)
        return rows, proof, calls

    def test_closed_all_window_avoids_live_ttl(self):
        rows, proof, calls = self.collect()
        self.assertTrue(proof['complete'])
        self.assertEqual(rows['fixture']['product'], '货币(Gold)')
        self.assertEqual(calls, [dict(profile='ALL', start='2026-11-05', end='2026-11-11')])

    def test_today_still_requires_live_ttl(self):
        rows, proof, _ = self.collect(end='2026-11-12')
        self.assertFalse(proof['complete'])
        self.assertFalse(rows)

    def test_fc27_exact_export_query_preserved(self):
        _, proof, calls = self.collect(profile='FC27')
        self.assertEqual(calls[0]['start'], '2026-11-01')
        self.assertEqual(calls[0]['end'], '2026-11-12')
        self.assertFalse(proof['complete'])

    def test_missing_and_partial_are_not_promoted(self):
        for options in (dict(missing=True), dict(partial=True)):
            with self.subTest(options=options):
                _, proof, _ = self.collect(**options)
                self.assertFalse(proof['complete'])


if __name__ == '__main__':
    unittest.main()
