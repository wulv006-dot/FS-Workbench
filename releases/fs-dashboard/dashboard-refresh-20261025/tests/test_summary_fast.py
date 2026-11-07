import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
import daily_archive
from live_summary import SummaryCache


class SummaryFast(unittest.TestCase):
    def test_native_admin_is_not_replaced_or_delayed_by_daily_derivation(self):
        cache = SummaryCache(Mock(), Mock(), {})
        self.addCleanup(cache.close)
        query = dict(profile='FC27', start='2026-10-01', end='2026-10-30', grain='day')
        value = dict(status='available', profile={'supplement': {'status': 'available'}}, sources={'Order': {'status': 'pending'}})
        cache.get_live = Mock(return_value=(200, value))
        old = dict(generatedAt='2026-01-01T00:00:00+00:00', sources={'Admin': {}})
        for archived in (None, old):
            with patch.object(daily_archive, 'read', return_value=archived), patch.object(daily_archive, 'derive_summary') as derive:
                code, result = cache.get(query)
                self.assertEqual(code, 200)
                self.assertIs(result, value)
                derive.assert_not_called()

    def test_daily_fallback_remains_available_while_native_pending(self):
        cache = SummaryCache(Mock(), Mock(), {})
        self.addCleanup(cache.close)
        query = dict(profile='FC27', start='2026-10-01', end='2026-10-30', grain='day')
        cache.get_live = Mock(return_value=(202, {'status': 'pending'}))
        derived = dict(archive={}, sources={'Admin': {}}, status='stale')
        with patch.object(daily_archive, 'read', return_value=None), patch.object(daily_archive, 'derive_summary', return_value=derived):
            code, result = cache.get(query)
            self.assertEqual(code, 200)
            self.assertTrue(result['stale'])
            self.assertEqual(result['query'], query)


if __name__ == '__main__':
    unittest.main()
