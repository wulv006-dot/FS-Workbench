import copy
import tempfile
import threading
import unittest
from pathlib import Path

from campaign_backend.analysis import AnalysisStore, reconcile
from campaign_backend.core import ContractError

START, END = '2026-10-23 00:00:00', '2026-10-23 23:59:59'


def order(number='PRIVATE_ORDER', amount='10.00', currency='GBP', state=1):
    return dict(id=1, site_id=266, order_no=number, pay_status=state, paytime='2026-10-23 10:00:00',
        currency_code=currency, pay_money_format2=[currency, amount], amount='99999',
        email='PRIVATE_EMAIL', note='PRIVATE_NOTE', discount_code='')


def log(number='PRIVATE_ORDER', native_id=123, log_id=1, status=1):
    return dict(id=log_id, site_id=266, order_no=number, coupon_id=native_id, status=status,
        use_time='2026-10-23 09:59:00', memberCoupon={'grant_batch_no': 'batch'},
        member={'email': 'PRIVATE_MEMBER'}, discount_amount='99999')


def bound(activity='activity-group', native_id='123', version='b1', kind='coupon'):
    return dict(activity_id=activity, binding_version=version, rule_version='r1', site_id='266',
        ref=dict(kind=kind, native_id=native_id, batch_id=None),
        valid_from='2026-10-01T00:00:00+08:00', valid_to='2026-11-01T00:00:00+08:00', page_id=None)


def config(bindings=None):
    return dict(bindings=bindings if bindings is not None else [bound()],
        source_utc_offset_minutes=480, time_verification_ref='fixture-time-only',
        money_verified=True, money_verification_ref='fixture-money-only', currency_scales={'GBP': 2, 'USD': 2})


class Reader:
    def __init__(self, orders=None, logs=None, discounts=None):
        self.source_orders = [order()] if orders is None else orders
        self.source_logs = [log()] if logs is None else logs
        self.discounts = discounts or {}

    def orders(self, *args):
        return copy.deepcopy(self.source_orders)

    def coupon_logs(self, *args):
        return copy.deepcopy(self.source_logs)

    def detail(self, kind, native_id):
        return self.discounts[native_id]

    def pages(self, resource, filters=(), validate=None):
        rows = list(self.discounts.values())
        if validate and any(not validate(row) for row in rows):
            raise ContractError('UPSTREAM_SCOPE_MISMATCH')
        return rows


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'analysis.sqlite3'
        self.store = AnalysisStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def sync(self, reader=None, settings=None):
        return reconcile(reader or Reader(), self.store, '266', START, END, settings or config())

    def test_actual_join_binding_and_currency_preserved_without_customer_output(self):
        result = self.sync()
        self.assertEqual(result['coverage']['bound_paid_orders'], 1)
        self.assertEqual(result['totals'][0]['currency'], 'GBP')
        self.assertEqual(result['totals'][0]['associated_paid_minor'], 1000)
        self.assertIsNone(result['totals'][0]['activity_paid_minor'])
        self.assertIsNone(result['totals'][0]['refund_minor'])
        self.assertIsNone(result['totals'][0]['net_minor'])
        self.assertNotIn('PRIVATE', str(result))
        self.assertNotIn('PRIVATE', str(self.store.db.execute('SELECT body FROM facts').fetchall()[0][0]))

    def test_generic_paid_coupon_without_real_project_binding_is_not_activity_sale(self):
        result = self.sync(settings=config([]))
        self.assertEqual(result['coverage']['associated_paid_observations'], 1)
        self.assertEqual(result['coverage']['unbound_paid_orders'], 1)
        self.assertEqual(result['coverage']['bound_paid_orders'], 0)
        self.assertEqual(result['totals'], [])
        self.assertEqual(result['activities'], [])
        self.assertIn('ACTIVITY_BINDINGS_REQUIRED', result['warnings'])

    def test_unverified_money_is_not_zero_and_other_amount_field_is_not_used(self):
        settings = config()
        settings['money_verified'] = False
        result = self.sync(settings=settings)
        self.assertIsNone(result['totals'][0]['associated_paid_minor'])
        self.assertEqual(result['totals'][0]['paid_orders'], 1)
        self.assertIn('PAID_MONEY_MAPPING_REQUIRED', result['warnings'])
        self.assertEqual(result['coverage']['bound_paid_orders'], 1)

    def test_duplicate_poll_restart_and_overlapping_windows_do_not_duplicate_facts(self):
        self.sync()
        self.store.close()
        self.store = AnalysisStore(self.path)
        result = self.sync()
        self.assertEqual(result['totals'][0]['paid_orders'], 1)
        self.assertEqual(result['coverage']['successful_runs'], 2)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM fact_history').fetchone()[0], 1)
        self.assertFalse(result['coverage']['history_complete'])
        self.assertEqual(result['coverage']['latest_window_end'], END)

    def test_multiple_activities_share_global_order_once_and_currencies_never_add(self):
        reader = Reader([order(), order('second', '20.00', 'USD')],
            [log(), log(native_id=456, log_id=2), log('second', log_id=3)])
        result = self.sync(reader, config([bound(), bound('other-activity', '456', 'b2')]))
        self.assertEqual({row['currency']: row['associated_paid_minor'] for row in result['totals']}, {'GBP': 1000, 'USD': 2000})
        self.assertEqual(sum(row['paid_orders'] for row in result['totals']), 2)
        self.assertEqual(len(result['activities']), 3)

    def test_one_binding_version_can_hold_multiple_exact_native_refs_but_membership_is_immutable(self):
        settings = config([bound(), bound(native_id='456')])
        result = self.sync(Reader([order()], [log(), log(native_id=456, log_id=2)]), settings)
        self.assertEqual(result['totals'][0]['paid_orders'], 1)
        self.assertEqual(len(result['activities']), 1)
        with self.assertRaisesRegex(ContractError, 'IMMUTABLE_BINDING_VERSION_CONFLICT'):
            self.sync(settings=config([bound()]))

    def test_missing_money_makes_aggregate_incomplete_not_partial_sum(self):
        bad = order('second')
        bad['pay_money_format2'] = ['WRONG', '10.00']
        result = self.sync(Reader([order(), bad], [log(), log('second', log_id=2)]))
        self.assertIsNone(result['totals'][0]['associated_paid_minor'])
        self.assertIsNone(result['activities'][0]['associated_paid_minor'])

    def test_failed_read_and_binding_conflict_preserve_last_successful_snapshot(self):
        previous = self.sync()
        reader = Reader()
        reader.coupon_logs = lambda *args: (_ for _ in ()).throw(ContractError('UPSTREAM_UNAVAILABLE'))
        with self.assertRaises(ContractError):
            self.sync(reader)
        current = self.store.summary('266')
        self.assertEqual(current['totals'], previous['totals'])
        self.assertEqual(current['verified_at'], previous['verified_at'])
        self.assertIn('LAST_RECONCILIATION_FAILED', current['warnings'])
        changed = config()
        changed['bindings'][0]['rule_version'] = 'different-rule'
        with self.assertRaisesRegex(ContractError, 'IMMUTABLE_BINDING_VERSION_CONFLICT'):
            self.sync(settings=changed)

    def test_late_payment_and_historical_refund_require_explicit_rescan_and_retain_history(self):
        self.sync(Reader([order(state=0)], [log(status=0)]))
        self.assertEqual(self.store.summary('266')['coverage']['bound_paid_orders'], 0)
        self.sync()
        settings = config()
        settings.update(refund_state_verified=True, refund_state_verification_ref='fixture-only', refunded_payment_states=[2])
        result = self.sync(Reader([order(state=2)], [log()]), settings)
        self.assertEqual(result['coverage']['refunded_observations'], 1)
        self.assertEqual(result['coverage']['bound_paid_orders'], 0)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM fact_history').fetchone()[0], 3)
        self.assertTrue(result['rescan_policy']['historical_refunds_require_rescan'])
        self.assertFalse(result['rescan_policy']['automatic_update_cursor_verified'])

    def test_unknown_payment_state_is_not_implicitly_refunded(self):
        for state in (99, '99', True, None, 2.0):
            with self.subTest(state=state):
                result = self.sync(Reader([order(state=state)], [log()]))
                self.assertIsNone(result['coverage']['refunded_observations'])
                self.assertIn('PAYMENT_STATE_UNKNOWN', result['warnings'])

    def test_verified_native_refund_status_excludes_sale_without_inventing_money(self):
        for state in (2, '2'):
            with self.subTest(state=state):
                self.sync()
                raw = order(state=state)
                raw.update(status=86, return_money='99999')
                result = self.sync(Reader([raw], [log()]))
                self.assertEqual(result['coverage']['refunded_observations'], 1)
                self.assertEqual(result['coverage']['paid_observations'], 0)
                self.assertEqual(result['coverage']['bound_paid_orders'], 0)
                self.assertEqual(result['totals'], [])
                self.assertNotIn('PAYMENT_STATE_UNKNOWN', result['warnings'])
                again = self.sync(Reader([raw], [log()]))
                self.assertEqual(again['coverage']['refunded_observations'], 1)
                self.assertEqual(self.store.db.execute('SELECT count(*) FROM facts').fetchone()[0], 1)
                self.assertTrue(result['rescan_policy']['historical_refunds_require_rescan'])

    def test_known_status_does_not_enable_refund_amount_or_line_allocation(self):
        result = self.sync(Reader([order(), order('refund', state=2)], [log(), log('refund', log_id=2)]))
        self.assertEqual(result['coverage']['refunded_observations'], 1)
        self.assertEqual(result['totals'][0]['associated_paid_minor'], 1000)
        self.assertIsNone(result['totals'][0]['refund_minor'])
        self.assertIsNone(result['totals'][0]['net_minor'])
        self.assertIsNone(result['totals'][0]['activity_paid_minor'])

    def test_foreign_or_unpaid_coupon_logs_and_unknown_status_never_attribute(self):
        for status in (0, 99):
            result = self.sync(Reader([order()], [log(status=status)]))
            self.assertEqual(result['totals'], [])
        bad = log()
        bad['site_id'] = 999
        with self.assertRaisesRegex(ContractError, 'COUPON_ORDER_SCOPE_MISMATCH'):
            self.sync(Reader([order()], [bad]))

    def test_discount_casefold_aliases_match_and_colliding_native_ids_stay_ambiguous(self):
        raw = order()
        raw['discount_code'] = ' summer '
        raw['applied_at'] = '2026-10-23 09:59:00'
        settings = config([bound('code-activity', '8', 'code-b1', 'discount')])
        settings.update(discount_applied_at_field='applied_at', discount_time_verification_ref='fixture-only')
        discounts = {'8': dict(id=8, site_id=266, code='SUMMER'), '9': dict(id=9, site_id=266, code='summer')}
        self.assertEqual(self.sync(Reader([raw], [], {'8': discounts['8']}), settings)['coverage']['bound_paid_orders'], 1)
        # Native ID9 is unbound but still makes a same-code native identity ambiguous.
        result = self.sync(Reader([raw], [], discounts), settings)
        self.assertEqual(result['coverage']['bound_paid_orders'], 0)
        self.assertIn('AMBIGUOUS_DISCOUNT_NATIVE_ID', result['warnings'])

    def test_older_concurrent_capture_cannot_overwrite_newer_success(self):
        entered, resume = threading.Event(), threading.Event()
        errors = []
        def worker():
            store = AnalysisStore(self.path)
            reader = Reader()
            original = reader.orders
            def delayed(*args):
                entered.set()
                if not resume.wait(5):
                    raise AssertionError('capture fixture not resumed')
                return original(*args)
            reader.orders = delayed
            try:
                reconcile(reader, store, '266', START, END, config())
            except ContractError as error:
                errors.append(str(error))
            finally:
                store.close()
        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(entered.wait(5))
        self.sync(Reader([order(amount='30.00')], [log()]))
        resume.set()
        thread.join(5)
        self.assertEqual(errors, ['STALE_ANALYSIS_CAPTURE'])
        self.assertEqual(self.store.summary('266')['totals'][0]['associated_paid_minor'], 3000)

    def test_in_memory_acceptance_supported_without_files_and_max_28_days_enforced(self):
        store = AnalysisStore(':memory:')
        try:
            self.assertEqual(reconcile(Reader(), store, '266', START, END, {})['coverage']['source_orders'], 1)
            with self.assertRaisesRegex(ContractError, 'MAX_28_DAY'):
                reconcile(Reader(), store, '266', '2026-09-01 00:00:00', END, {})
        finally:
            store.close()


if __name__ == '__main__':
    unittest.main()
