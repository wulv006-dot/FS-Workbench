"""Cohort and refresh regression tests using synthetic private order evidence."""
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1] / 'source'))
sys.path.insert(0, str(HERE.parents[2] / 'user-analytics-20261022' / 'source'))

from vip_followup import SHANGHAI, midnight, project_order, read_cohort, read_period, refresh_buyers, refresh_period, snapshot_evidence

ANCHOR = date(2026, 11, 16)
NOW = midnight(ANCHOR) + timedelta(hours=9)


def order(identifier, offset, dollars, *, country='GB', uid='71', address='buyer@example.test',
          state='已完成', pay='1', customer=None, es=()):
    raw = dict(id=identifier, order_no=f'example-{identifier}', paytime=(NOW + timedelta(days=offset)).isoformat(),
               pay_status=pay, status_format=state, amount_usd_format=dollars, country_code=country,
               uid=uid, email=address)
    return project_order(raw, customer=customer, es_buyers=es)


def cohort(rows, *, missing=()):
    def read(start, end, now):
        return rows, dict(nativeMissingDays=missing, esCoverage={'complete': True})
    return read_cohort(anchor=ANCHOR, now=NOW, archive_reader=read)


class VipFollowupTests(unittest.TestCase):
    def test_full_window_paid_usd_qualifies_when_each_half_is_below_threshold(self):
        rows = [order(1, -30, '125.55', country='GB'), order(2, -15, '174.45', country='US',
                state='已退款·部分退款', pay='2'), order(3, -14, '20', country='CA')]
        result = cohort(rows)
        buyer, = result['buyers']
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['windows']['firstHalf'],
                         {'start': '2026-10-17', 'endExclusive': '2026-11-01'})
        self.assertEqual(buyer['windows']['month']['salesUsd'], '300.00')
        self.assertEqual(buyer['windows']['month']['refundMarkedOriginalPaidUsd'], '174.45')
        self.assertIsNone(buyer['windows']['month']['knownSettledRefundUsd'])
        self.assertFalse(buyer['windows']['firstHalf']['qualified'])
        self.assertFalse(buyer['windows']['secondHalf']['qualified'])
        self.assertEqual(buyer['paymentCountries'], ['GB', 'US'])
        self.assertEqual(buyer['lastOrder']['orderNo'], 'example-3')
        self.assertEqual(buyer['daysSinceLastPaid'], 14)
        self.assertEqual(buyer['followUpStatus'], 'recent')

    def test_conflicting_es_groups_never_add_another_verified_customer_spend(self):
        result = cohort([order(1, -20, '200', es={'same-opaque'}),
                         order(2, -17, '250', uid='72', address='other@example.test', es={'same-opaque'})])
        self.assertEqual(result['buyers'], [])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['coverage']['identityConflictOrders'], 2)

    def test_shared_email_or_customer_id_never_merges_distinct_native_uids(self):
        result = cohort([order(1, -20, '301', customer='email-derived'),
                         order(2, -19, '190', uid='72', customer='email-derived'),
                         order(3, -18, '125', uid=None, customer='email-derived')])
        buyer, = result['buyers']
        self.assertEqual(buyer['uid'], '71')
        self.assertEqual(buyer['windows']['month']['salesUsd'], '301.00')
        self.assertIsNone(buyer['email'])
        self.assertEqual(buyer['identity']['emails'], [])
        self.assertEqual(buyer['identity']['customerIds'], [])
        self.assertEqual(result['coverage']['identityConflictOrders'], 3)
        self.assertEqual(result['coverage']['unknownIdentityOrders'], 1)

    def test_scoped_identity_conflict_does_not_stop_unrelated_due_buyer(self):
        rows = [order(1, -20, '100'), order(2, -18, '105', uid='72'), order(3, -17, '110', uid=None),
                order(4, -16, '330', uid='73', address='separate@example.test')]
        result = cohort(rows)
        self.assertEqual(result['coverage']['unknownIdentityOrders'], 1)
        refresh = refresh_buyers(result['buyers'], since=midnight(ANCHOR), now=NOW, live_reader=lambda *_: [])
        buyer, = refresh['buyers']
        self.assertEqual(buyer['uid'], '73')
        self.assertEqual(buyer['followUpStatus'], 'due')

    def test_refresh_uses_any_country_and_same_order_refund_recheck(self):
        initial = cohort([order(1, -15, '300', customer='private-fixture')])['buyers']
        since = midnight(ANCHOR)
        first = refresh_buyers(initial, since=since, now=NOW, live_reader=lambda *_: [])
        old, = first['buyers']
        self.assertEqual(old['daysSinceLastPaid'], 15)
        self.assertEqual(old['followUpStatus'], 'due')
        payment = order(2, 0, '30', country='CA', state='问题订单')
        returned, = refresh_buyers(first['buyers'], since=since, now=NOW,
                                   live_reader=lambda *_: [payment])['buyers']
        self.assertEqual(returned['followUpStatus'], 'recent')
        self.assertEqual(returned['lastOrder']['afterSales'], 'problem')
        refund = order(2, 0, '30', country='CA', state='已退款·全额退款', pay='2')
        checked, = refresh_buyers([returned], since=since, now=NOW,
                                  live_reader=lambda *_: [refund])['buyers']
        self.assertEqual(len(checked['history']), 2)
        self.assertEqual(checked['lastOrder']['amountUsd'], '30')
        self.assertEqual(checked['lastOrder']['refundStatus'], 'full_observed')
        self.assertEqual(checked['windows']['month']['salesUsd'], '300.00')

    def test_unverified_identity_or_missed_date_keeps_existing_buyer_without_due_status(self):
        rows = [order(1, -19, '301'), order(2, -20, '306', uid=None, address=None, es={'es-only'})]
        missing = [(ANCHOR - timedelta(days=2)).isoformat()]
        initial = cohort(rows, missing=missing)
        since = midnight(ANCHOR)
        self.assertFalse(initial['coverage']['datesComplete'])
        refresh = refresh_buyers(initial['buyers'], since=since, now=NOW, live_reader=lambda *_: [])
        self.assertEqual(len(refresh['buyers']), 2)
        self.assertEqual([r['followUpStatus'] for r in refresh['buyers']], ['unknown', 'unknown'])
        self.assertTrue(all(r['paymentCoverage']['through'] is None for r in refresh['buyers']))
        self.assertTrue(all(r['paymentCoverage']['observedThrough'] for r in refresh['buyers']))

    def test_conflicting_live_uid_is_not_attached_by_email(self):
        initial = cohort([order(1, -18, '301')])['buyers']
        result = refresh_buyers(initial, since=midnight(ANCHOR), now=NOW,
                                live_reader=lambda *_: [order(2, 0, '50', uid='32')])
        buyer, = result['buyers']
        self.assertEqual(result['coverage']['identityConflictBuyers'], 1)
        self.assertEqual(buyer['followUpStatus'], 'unknown')
        self.assertEqual(buyer['lastOrder']['orderNo'], 'example-1')

    def test_guest_email_does_not_merge_live_orders_with_different_positive_uids(self):
        initial = cohort([order(1, -18, '301', uid=None)])['buyers']
        result = refresh_buyers(initial, since=midnight(ANCHOR), now=NOW,
                                live_reader=lambda *_: [order(2, 0, '50', uid='32'),
                                                         order(3, 0, '50', uid='33')])
        buyer, = result['buyers']
        self.assertEqual(result['coverage']['identityConflictBuyers'], 1)
        self.assertEqual(result['coverage']['matchedOrders'], 0)
        self.assertEqual(buyer['followUpStatus'], 'unknown')
        self.assertEqual(buyer['lastOrder']['orderNo'], 'example-1')

    def test_es_buyer_label_requires_exact_same_order_time_and_single_site(self):
        number, paid = 'example-1', '2026-11-15 02:00:00'
        digest = sha256(number.encode()).hexdigest()
        result = dict(rows=[dict(order_no=number, site_id='266', gid='1327', paytime=paid)],
                      dataset={'rows': [
                          {'订单号': digest, '游戏': 'FC27', '付款时间': paid.replace('-', '/'), 'buyer_id': 'matched'},
                          {'订单号': digest, '游戏': 'FC27', '付款时间': '2026-11-15 02:01:00', 'buyer_id': 'other'},
                      ]}, identity_catalog={'rows': []})
        self.assertEqual(snapshot_evidence(result)[number][1], {'matched'})
        result['identity_catalog']['rows'] = [dict(order_no=number, site_id='123')]
        self.assertEqual(snapshot_evidence(result)[number][1], set())

    def test_custom_period_includes_both_dates_and_passes_historical_cutoff_to_refresh(self):
        start, end = ANCHOR - timedelta(days=23), ANCHOR - timedelta(days=19)
        historic_cutoff = NOW - timedelta(days=2)
        rows = [order(1, -23, '100'), order(2, -21, '150'), order(3, -19, '50')]

        def archive(from_day, to_day, now):
            self.assertEqual((from_day, to_day, now), (start, end + timedelta(days=1), historic_cutoff))
            return rows, dict(nativeMissingDays=[], esCoverage={'complete': True})

        def activity(buyers, *, since, now):
            self.assertEqual((since, now), (midnight(end + timedelta(days=1)), historic_cutoff))
            return refresh_buyers(buyers, since=since, now=now,
                                  live_reader=lambda *_: [order(4, -3, '20', country='CA')])

        result = read_period(start=start, end=end, now=historic_cutoff, archive_reader=archive, activity_reader=activity)
        buyer, = result['buyers']
        self.assertEqual(buyer['windows']['firstHalf']['salesUsd'], '250.00')
        self.assertEqual(buyer['windows']['secondHalf']['salesUsd'], '50.00')
        self.assertEqual(buyer['lastOrder']['orderNo'], 'example-4')
        self.assertEqual(buyer['daysSinceLastPaid'], 1)

    def test_single_custom_day_has_only_a_first_half(self):
        day = ANCHOR - timedelta(days=1)
        result = read_period(start=day, end=day, now=NOW,
                             archive_reader=lambda *_: ([order(1, -1, '300')],
                                                         dict(nativeMissingDays=[], esCoverage={'complete': True})),
                             activity_reader=lambda buyers, **kw: refresh_buyers(
                                 buyers, live_reader=lambda *_: [], **kw))
        self.assertIsNone(result['windows']['secondHalf'])
        self.assertIsNone(result['buyers'][0]['windows']['secondHalf'])
        with self.assertRaisesRegex(ValueError, 'vip_period_dates'):
            read_period(start=day, end=NOW.date(), now=NOW)

    def test_period_activity_reads_historical_cutoff_only_from_native_archive(self):
        today = datetime.now(SHANGHAI).date()
        cutoff = midnight(today - timedelta(days=2)) + timedelta(hours=12)
        since = midnight(cutoff.date() - timedelta(days=25))
        buyers = cohort([order(1, -15, '300')])['buyers']

        def archive(start, end, stop, *, wanted):
            self.assertEqual((start, end, stop), (since.date(), cutoff.date() + timedelta(days=1),
                                                 cutoff + timedelta(seconds=1)))
            self.assertIn(('uids', '71'), wanted)
            return [], dict(nativeMissingDays=[cutoff.date().isoformat()])

        def unexpected_admin(*args):
            self.fail('historical closed dates must not read the live Admin')

        result = refresh_period(buyers, since=since, now=cutoff, archive_reader=archive, live_reader=unexpected_admin)
        self.assertEqual(result['coverage']['missingDays'], [cutoff.date().isoformat()])
        self.assertFalse(result['buyers'][0]['paymentCoverage']['complete'])

    def test_refund_recheck_reads_only_exact_original_outside_incremental_window(self):
        original = order(1, -15, '300')
        buyers = cohort([original])['buyers']
        since = midnight(ANCHOR)

        def live(from_time, now):
            self.assertEqual(from_time, since)
            return []

        def exact(orders, now):
            self.assertEqual(orders, [original])
            return [order(1, -15, '300', pay='2', state='已退款')]

        refreshed = refresh_buyers(buyers, since=since, now=NOW, live_reader=live,
                                   recheck_orders=[original], recheck_reader=exact)
        self.assertTrue(refreshed['coverage']['refundReadback']['complete'])
        self.assertEqual(refreshed['coverage']['paidOrders'], 0)
        buyer, = refreshed['buyers']
        self.assertEqual(buyer['lastOrder']['refundStatus'], 'marked_amount_unknown')
        self.assertEqual(buyer['lastOrder']['refundReadback']['status'], 'verified')
        self.assertEqual(buyer['followUpStatus'], 'due')
        reloaded = refresh_buyers([buyer], since=since, now=NOW, live_reader=live,
                                  recheck_orders=[original], recheck_reader=lambda *_: [])
        self.assertFalse(reloaded['coverage']['refundReadback']['complete'])
        self.assertTrue(reloaded['buyers'][0]['paymentCoverage']['complete'])
        self.assertEqual(reloaded['buyers'][0]['lastOrder']['refundReadback']['status'], 'missing')
        self.assertEqual(reloaded['buyers'][0]['lastOrder']['refundStatus'], 'marked_amount_unknown')


if __name__ == '__main__':
    unittest.main()
