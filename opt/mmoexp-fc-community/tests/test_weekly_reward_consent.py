import datetime as dt
import tempfile
import unittest
from pathlib import Path

from weekly_reward_consent import RETENTION_SECONDS, WeeklyRewardConsent, current_week


class WeeklyConsentTests(unittest.TestCase):
    def test_london_week_boundary_and_one_way_storage(self):
        sunday = dt.datetime(2026, 11, 15, 23, 59, tzinfo=dt.timezone.utc).timestamp()
        monday = dt.datetime(2026, 11, 16, 0, 0, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(current_week(sunday), '2026-W46')
        self.assertEqual(current_week(monday), '2026-W47')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'consent.sqlite3'
            consent = WeeklyRewardConsent(path, 'test-key-' * 5)
            consent.agree('1041923524601851914', '333333333333333333', now=sunday)
            self.assertTrue(consent.has_consent('1041923524601851914',
                                                '333333333333333333', '2026-W46'))
            self.assertFalse(consent.has_consent('1041923524601851914',
                                                 '333333333333333333', '2026-W47'))
            self.assertNotIn(b'333333333333333333', path.read_bytes())
            consent.withdraw('1041923524601851914', '333333333333333333', now=sunday)
            self.assertFalse(consent.has_consent('1041923524601851914',
                                                 '333333333333333333', '2026-W46'))

    def test_requires_separate_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                WeeklyRewardConsent(Path(tmp) / 'consent.sqlite3', 'short')

    def test_old_opt_in_is_removed(self):
        now = dt.datetime(2026, 11, 17, tzinfo=dt.timezone.utc).timestamp()
        old = now - RETENTION_SECONDS - 1
        with tempfile.TemporaryDirectory() as tmp:
            consent = WeeklyRewardConsent(Path(tmp) / 'consent.sqlite3', 'test-key-' * 5)
            consent.agree('1041923524601851914', '333333333333333333', now=old)
            self.assertTrue(consent.has_consent('1041923524601851914',
                                                '333333333333333333', current_week(old)))
            consent.purge_expired(now)
            self.assertFalse(consent.has_consent('1041923524601851914',
                                                 '333333333333333333', current_week(old)))


if __name__ == '__main__':
    unittest.main()
