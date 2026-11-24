"""Program-review behavior with synthetic Admin and private projection records."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))

from maintenance_review import coupon_evidence, manual_evidence, review_evidence


class ReviewTest(unittest.TestCase):
    def test_order_owner_precedes_uid_and_only_unique_uids_fall_back(self):
        orders = [
            {'order_no': 'A', 'uid': '1', 'customer_id': 'alice'},
            {'order_no': 'B', 'uid': '2', 'customer_id': 'bob'},
            {'order_no': 'C', 'uid': '2', 'customer_id': 'carol'},
        ]
        logs = [
            {'id': 1, 'order_no': 'A', 'member_id': 2},
            {'id': 2, 'order_no': 'unpaid', 'member_id': 1},
            {'id': 3, 'order_no': 'unpaid2', 'member_id': 2},
            {'id': 4, 'member_id': 3},
        ]
        actual = coupon_evidence(orders, logs, 'alice')
        self.assertEqual([1, 2], [row['id'] for row in actual['matched']])
        self.assertEqual(2, actual['unattributed'])
        self.assertEqual([], coupon_evidence(orders, logs, 'bob')['matched'])

    def test_unattributed_rows_are_a_gap_and_do_not_hold(self):
        coupons = coupon_evidence([], [{'id': 1, 'member_id': 3}], 'alice')
        result = review_evidence(coupons=coupons, payments=[], exceptions=[], automatic=[], contacts=[])
        self.assertEqual('pass', result['decision'])
        self.assertEqual(1, result['unattributed_coupon_logs'])
        self.assertIn('1 条用券记录无法归属客户', result['manual_coupon_notice'])

    def test_which_check_held_and_actual_coupon_rows_are_hashed(self):
        base = dict(coupons=coupon_evidence([], [], 'alice'),
                    payments=[], exceptions=[], automatic=[], contacts=[])
        before = review_evidence(**base)
        for field in ('payments', 'exceptions', 'automatic', 'contacts'):
            with self.subTest(field=field):
                result = review_evidence(**dict(base, **{field: [{'id': 1}]}))
                self.assertEqual('hold', result['decision'])
                self.assertEqual([field], result['reasons'])
        orders = [{'order_no': 'A', 'customer_id': 'alice'}]
        for log_id in (10, 11):
            result = review_evidence(**dict(base, coupons=coupon_evidence(
                orders, [{'id': log_id, 'order_no': 'A'}], 'alice')))
            self.assertEqual('hold', result['decision'])
            self.assertEqual(['manual_coupons'], result['reasons'])
            self.assertNotEqual(before['digest'], result['digest'])
            before = result

    def test_missing_evidence_cannot_become_a_pass(self):
        with self.assertRaises(ValueError):
            review_evidence(coupons=None, payments=[], exceptions=[], automatic=[], contacts=[])

class ManualGrantTest(unittest.TestCase):
    def test_window_covers_all_statuses_except_own_batches_and_other_sites(self):
        now = datetime(2026, 11, 24, 12, tzinfo=timezone(timedelta(hours=8)))
        cutoff = now - timedelta(days=30)
        def row(ident, at, **fields):
            return dict(dict(id=ident, site_id=266, member_id=10, start_time=at.isoformat(),
                             grant_batch_no='MANUAL', status=ident % 3), **fields)
        rows = [row(1, cutoff), row(2, cutoff + timedelta(seconds=1)),
                row(3, now), row(4, now - timedelta(days=1)),
                row(5, now, grant_batch_no='FCSM_' + 'A' * 32),
                row(6, now, site_id=100), row(7, now + timedelta(seconds=1))]
        actual = manual_evidence(
            [{'customer_id': 'c1', 'uid': 10}], 'c1', now, lambda uid: rows)
        self.assertEqual({2, 3, 4}, {row['id'] for row in actual['matched']})
        self.assertEqual([], actual['uid_gaps'])
        self.assertNotIn('仅核对已使用记录', actual['notice'])

    def test_ambiguous_uid_is_a_gap_and_never_queried(self):
        now = datetime(2026, 11, 24, tzinfo=timezone.utc)
        orders = [{'customer_id': 'c1', 'uid': 10}, {'customer_id': 'c2', 'uid': 10}]
        def unexpected(uid):
            self.fail('ambiguous UID was queried')
        actual = manual_evidence(orders, 'c1', now, unexpected,
                                 coupon_evidence([], [{'id': 42}], 'c1'))
        self.assertEqual(['10'], actual['uid_gaps'])
        self.assertEqual([], actual['matched'])
        self.assertIn('仅核对已使用记录', actual['notice'])
        self.assertIn('1 条用券记录无法归属客户', actual['notice'])
        result = review_evidence(coupons=actual, payments=[], exceptions=[], automatic=[], contacts=[])
        self.assertEqual('pass', result['decision'])

    def test_known_uid_read_failure_propagates_instead_of_confirming_no_coupon(self):
        now = datetime(2026, 11, 24, tzinfo=timezone.utc)
        def denied(uid):
            raise OSError('fixture denied')
        with self.assertRaises(OSError):
            manual_evidence([{'customer_id': 'c1', 'uid': 10}], 'c1', now, denied)
