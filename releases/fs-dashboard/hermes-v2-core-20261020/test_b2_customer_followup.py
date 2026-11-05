"""Frozen synthetic B2 cases; no raw customer identity or external calls."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parent / "source"))
from b2_customer_followup import Observation, assess


class B2Contracts(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 31, 10, tzinfo=timezone.utc)
        self.anchor = self.now - timedelta(days=5)
        self.o = Observation("e1", "synthetic_admin", "v1", self.now, True, True,
                             first_paid_at=self.now-timedelta(days=20), latest_paid_at=self.anchor)

    def check(self, observation=None, **changes):
        args = dict(now=self.now, observation_anchor=self.anchor,
                    recheck_at=self.now+timedelta(days=1))
        args.update(changes)
        return assess(observation or self.o, **args)

    def test_partial_identity_and_required_history_need_evidence(self):
        for change in (dict(complete=False), dict(identity_verified=False),
                       dict(missing=("effective_order_policy",))):
            self.assertEqual(self.check(replace(self.o, **change))["state"], "needs_evidence")

    def test_financial_limitations_preserve_due_and_freshness_checks(self):
        missing = ("purchase_cost", "net_contribution", "complete_refund_change_cursor")
        o = replace(self.o, missing=missing, refund_review_needed=True, latest_paid_at=self.now-timedelta(days=1))
        value = self.check(o, recheck_at=self.now)
        self.assertEqual(value["state"], "review_due")
        self.assertTrue(value["purchase_since_anchor"])
        self.assertEqual(value["limitations"], list(missing))
        self.assertTrue(value["refund_review_needed"])
        self.assertEqual(value["maturity"], {"7": None, "14": None, "30": None})
        self.assertFalse(value["business_write_performed"])
        self.assertEqual(self.check(replace(o, as_of=self.now-timedelta(hours=1)), recheck_at=self.now)["state"], "refresh_required")

    def test_due_without_new_purchase(self):
        value = self.check(recheck_at=self.now)
        self.assertEqual(value["state"], "review_due")
        self.assertEqual(value["options"][0]["action"], "no_intervention")
        self.assertFalse(value["business_write_performed"])

    def test_same_evidence_suppressed_until_due(self):
        self.assertEqual(self.check(previous_evidence_ref="e1")["state"], "waiting")
        self.assertEqual(self.check(previous_evidence_ref="e1", recheck_at=self.now)["state"], "review_due")

    def test_stale_cutoff_requires_refresh(self):
        stale = replace(self.o, as_of=self.now-timedelta(hours=2))
        self.assertEqual(self.check(stale, recheck_at=self.now)["state"], "refresh_required")

    def test_sparse_history_does_not_invent_cadence(self):
        self.assertEqual(self.check()["reason"], "purchase_cadence_not_established")

    def test_supplied_cadence_changes_conclusion(self):
        self.assertEqual(self.check(expected_next_purchase_at=self.now+timedelta(days=4))["state"], "waiting")
        self.assertEqual(self.check(expected_next_purchase_at=self.now-timedelta(days=1))["state"], "investigate")

    def test_cadence_trigger_does_not_require_new_evidence_id(self):
        self.assertEqual(self.check(previous_evidence_ref="e1", expected_next_purchase_at=self.now)["state"], "investigate")

    def test_purchase_observation_does_not_claim_effect(self):
        value = self.check(replace(self.o, latest_paid_at=self.now))
        self.assertEqual(value["state"], "purchase_observed")
        self.assertNotIn("incremental_revenue", value)

    def test_stopped_goal_stays_stopped(self):
        self.assertEqual(self.check(goal_active=False)["state"], "stopped")

    def test_maturity_requires_the_full_elapsed_observation_window(self):
        first = datetime(2026, 10, 1, 23, 55, tzinfo=timezone(timedelta(hours=8)))
        cases = (
            (datetime(2026, 10, 8, 0, 0, tzinfo=first.tzinfo), {"7": False, "14": False, "30": False}),
            (datetime(2026, 10, 8, 23, 54, tzinfo=first.tzinfo), {"7": False, "14": False, "30": False}),
            (datetime(2026, 10, 8, 23, 55, tzinfo=first.tzinfo), {"7": True, "14": False, "30": False}),
            (datetime(2026, 10, 8, 15, 54, tzinfo=timezone.utc), {"7": False, "14": False, "30": False}),
            (datetime(2026, 10, 8, 15, 55, tzinfo=timezone.utc), {"7": True, "14": False, "30": False}),
            (datetime(2026, 10, 15, 23, 54, tzinfo=first.tzinfo), {"7": True, "14": False, "30": False}),
            (datetime(2026, 10, 15, 23, 55, tzinfo=first.tzinfo), {"7": True, "14": True, "30": False}),
            (datetime(2026, 10, 31, 23, 54, tzinfo=first.tzinfo), {"7": True, "14": True, "30": False}),
            (datetime(2026, 10, 31, 23, 55, tzinfo=first.tzinfo), {"7": True, "14": True, "30": True}))
        for cutoff, expected in cases:
            with self.subTest(cutoff=cutoff):
                o = replace(self.o, as_of=cutoff, first_paid_at=first, latest_paid_at=first)
                value = self.check(o, now=cutoff, observation_anchor=first, recheck_at=cutoff+timedelta(days=1))
                self.assertEqual(value["maturity"], expected)

    def test_maturity_uses_source_cutoff_not_current_time(self):
        o = replace(self.o, first_paid_at=self.now-timedelta(days=7),
                    latest_paid_at=self.now-timedelta(days=7), as_of=self.now-timedelta(days=1))
        self.assertFalse(self.check(o)["maturity"]["7"])
        self.assertEqual(self.check(replace(o, complete=False))["maturity"]["7"], None)

    def test_missing_or_corrected_first_payment_does_not_publish_maturity(self):
        old = replace(self.o, first_paid_at=self.now-timedelta(days=35))
        for change, expected in ((dict(missing=("first_paid_history",)), "needs_evidence"),
                                 (dict(refund_review_needed=True), "investigate")):
            with self.subTest(change=change):
                value = self.check(replace(old, **change))
                self.assertEqual(value["state"], expected)
                self.assertEqual(value["maturity"], {"7": None, "14": None, "30": None})

    def test_earlier_purchase_does_not_suppress_due_recheck(self):
        old = replace(self.o, latest_paid_at=self.now-timedelta(days=4),
                      as_of=self.now-timedelta(days=2))
        value = self.check(old, previous_evidence_ref="e1", recheck_at=self.now)
        self.assertEqual(value["state"], "refresh_required")
        self.assertTrue(value["purchase_since_anchor"])
        fresh = self.check(replace(old, as_of=self.now), previous_evidence_ref="e1", recheck_at=self.now)
        self.assertEqual(fresh["state"], "review_due")
        self.assertTrue(fresh["purchase_since_anchor"])

    def test_earlier_purchase_does_not_suppress_cadence_trigger(self):
        old = replace(self.o, latest_paid_at=self.now-timedelta(days=4),
                      as_of=self.now-timedelta(days=2))
        value = self.check(old, previous_evidence_ref="e1", expected_next_purchase_at=self.now)
        self.assertEqual(value["state"], "refresh_required")
        fresh = self.check(replace(old, as_of=self.now), previous_evidence_ref="e1",
                           expected_next_purchase_at=self.now)
        self.assertEqual(fresh["state"], "investigate")
        self.assertTrue(fresh["purchase_since_anchor"])

    def test_future_naive_and_inverted_history_rejected(self):
        for o in (replace(self.o, as_of=self.now+timedelta(seconds=1)),
                  replace(self.o, as_of=self.now.replace(tzinfo=None)),
                  replace(self.o, first_paid_at=self.now),
                  replace(self.o, latest_paid_at=self.now+timedelta(seconds=1))):
            with self.assertRaises(ValueError):
                self.check(o)


class CurrentFSConsumer(unittest.TestCase):
    """Real current A2 Store/Service/context; only invented source orders."""
    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'user-analytics-20261022/tests'))
        import test_a2_query_context as a2
        import b2_customer_followup as b2
        self.b2 = b2
        self.a = a2.A2Context()
        self.addCleanup(self.a.doCleanups)
        self.a.setUp()
        self.addCleanup(self.a.tearDown)
        self.summary = self.a.summary()
        self.snapshot = self.a.snapshot(self.summary)
        self.customer = max(self.a.context.candidates(self.snapshot)['rows'],
                            key=lambda row: row['purchases']['covered_history_orders'])['opaque_customer_id']

    def describe(self):
        return self.b2.describe_customer(self.a.context, snapshot_id=self.snapshot,
                                         customer_id=self.customer, now=self.a.original.clock())

    def test_real_current_frozen_projection_supports_ordinary_question_without_goal(self):
        import json
        from unittest.mock import patch
        with patch.object(self.a.context, 'timeline', wraps=self.a.context.timeline) as read:
            value = self.describe()
        read.assert_called_once_with(self.snapshot, self.customer, limit=1)
        self.assertEqual(value['customer_id'], self.customer)
        self.assertEqual(value['source']['policy_version'], self.summary['source']['policy_version'])
        self.assertEqual(value['source']['query'], self.summary['source']['query'])
        self.assertEqual(value['facts']['covered_history_orders'], 2)
        self.assertEqual(value['facts']['first_paid_at'], '2026-10-02T00:00:00+08:00')
        self.assertFalse(value['business_write_performed'])
        self.assertTrue(value['refund_review_needed'])
        for forbidden in ('@example.test', 'synthetic-', 'goal_id', 'request_id', 'recheck_at', 'net_profit'):
            self.assertNotIn(forbidden, json.dumps(value))

    def test_current_a2_limitations_do_not_cancel_a_due_readonly_review(self):
        now = self.a.original.clock()
        receipt = self.a.context.timeline(self.snapshot, self.customer)
        observation = self.b2.observation_from_a2(receipt, now=now)
        self.assertTrue(observation.complete)
        self.assertTrue(observation.refund_review_needed)
        self.assertIn("purchase_cost", observation.missing)
        result = self.b2.assess(observation, now=now,
                                observation_anchor=observation.as_of-timedelta(days=5),
                                recheck_at=observation.as_of)
        self.assertEqual(result["state"], "review_due")
        self.assertEqual(result["limitations"], list(observation.missing))
        self.assertTrue(result["refund_review_needed"])
        self.assertFalse(result["business_write_performed"])
        self.assertEqual(result["maturity"], {"7": None, "14": None, "30": None})

    def test_period_first_seen_never_becomes_lifetime_first(self):
        self.snapshot = self.a.snapshot(self.a.context.aggregate({'start': '2026-10-01'}))
        value = self.describe()
        self.assertIsNone(value['facts']['first_paid_at'])
        self.assertIsNotNone(value['facts']['observed_first_at'])
        self.assertIn('historical_first_purchase_unverified', value['limitations'])

    def test_snapshot_read_at_is_not_effective_source_cutoff(self):
        from copy import deepcopy
        receipt = deepcopy(self.a.context.timeline(self.snapshot, self.customer))
        receipt['source']['weekly_cutoff'] = '2026-10-21T00:00:00+08:00'
        observation = self.b2.observation_from_a2(receipt, now=self.a.original.clock())
        self.assertEqual(observation.as_of.isoformat(), '2026-10-21T00:00:00+08:00')

    def test_source_and_host_permissions_are_live_literal_true(self):
        self.a.host_allowed = False
        with self.assertRaises(PermissionError):
            self.describe()
        self.a.host_allowed = True
        self.a.source_allowed = False
        with self.assertRaises(PermissionError):
            self.describe()
        self.a.source_allowed = True
        self.a.context.validate = lambda *args: 1
        with self.assertRaises(PermissionError):
            self.describe()

    def test_coverage_and_first_flags_cannot_promote_partial_history(self):
        from copy import deepcopy
        receipt = deepcopy(self.a.context.timeline(self.snapshot, self.customer))
        receipt['source']['coverage']['period_complete'] = False
        o = self.b2.observation_from_a2(receipt, now=self.a.original.clock())
        self.assertFalse(o.complete)
        self.assertIsNone(o.first_paid_at)
        receipt['source']['coverage']['period_complete'] = True
        receipt['customer']['first_paid']['complete'] = 1
        o = self.b2.observation_from_a2(receipt, now=self.a.original.clock())
        self.assertIsNone(o.first_paid_at)

    def test_receipt_customer_and_snapshot_must_match_requested_scope(self):
        from copy import deepcopy
        from unittest.mock import patch
        receipt = deepcopy(self.a.context.timeline(self.snapshot, self.customer))
        for change in ('customer', 'snapshot'):
            altered = deepcopy(receipt)
            if change == 'customer':
                altered['customer']['opaque_customer_id'] = 'c_' + 'a' * 32
            else:
                altered['source']['snapshot_id'] = 'us_' + 'a' * 32
            with patch.object(self.a.context, 'timeline', return_value=altered):
                with self.assertRaises(PermissionError):
                    self.describe()

    def test_live_pages_cannot_be_misread_as_complete_frozen_lifecycle(self):
        with self.assertRaisesRegex(ValueError, 'a2_customer_receipt'):
            self.b2.observation_from_a2({'status': 'partial', 'semantics': 'live_non_snapshot',
                                        'complete': False, 'data': [], 'next_cursor': None},
                                       now=self.a.original.clock())

    def test_current_refund_and_invalid_order_policy_is_owned_by_real_FS(self):
        import test_a2_query_context as a2
        self.a.rows = [a2.order(10), a2.order(11, paid='2'),
                       dict(a2.order(12, paid='2'), status='86'),
                       dict(a2.order(13), status='22')]
        self.a.load()
        self.snapshot = self.a.snapshot(self.a.summary())
        self.customer = self.a.cid(self.snapshot)
        value = self.describe()
        self.assertEqual(value['facts']['covered_history_orders'], 1)
        self.assertEqual(value['facts']['covered_history_sales_usd'], '10.25')

    def test_explicit_tracking_reuses_goal_state_and_original_pending_id(self):
        from b2_goal_state import create_goal, plan_step
        now = self.a.original.clock()
        o = self.b2.observation_from_a2(self.a.context.timeline(self.snapshot, self.customer), now=now)
        evidence = [dict(ref=o.evidence_ref, source=o.source, as_of=o.as_of.isoformat(),
                         coverage='frozen_source_scope', missing=list(o.missing), version=o.version)]
        goal = create_goal(goal_id='explicit-synthetic-followup', owner='operator',
                           scope_ref='project:1327', objective='Review source changes only',
                           constraints=['No business writes'], recheck_at=now+timedelta(days=1),
                           now=now, explicit_goal=True, authorize=lambda *args: True)
        first = plan_step(goal, expected_revision=goal['revision'], now=now,
                          fact_version=o.version, request_id='original-followup', evidence=evidence,
                          authorize=lambda *args: True)
        pending = first['state']
        second = plan_step(pending, expected_revision=pending['revision'], now=now+timedelta(days=2),
                           fact_version=o.version+'-changed', request_id='must-not-dispatch',
                           evidence=evidence, authorize=lambda *args: True)
        self.assertEqual(second['action'], 'reconcile_original')
        self.assertEqual(second['request_id'], 'original-followup')
        self.assertIsNone(second['handoff'])
        self.assertEqual(second['state'], pending)


class CurrentFSLiveConsumer(unittest.TestCase):
    def setUp(self):
        import b2_customer_followup as b2
        self.b2 = b2
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tiered-data-access-20261101/source'))
        self.now = datetime(2026, 11, 3, tzinfo=timezone.utc)

    def observe(self, fetch, **changes):
        arguments = dict(customer_id='c_'+'a'*32, site_id='266', game_id='1327',
                         start='2026-10-01', end_exclusive='2026-10-30', max_pages=4, now=self.now)
        arguments.update(changes)
        return self.b2.observe_live_orders(fetch, **arguments)

    def test_current_20_row_cursor_and_28_day_windows_are_serial_not_lifetime_history(self):
        import json
        calls = []
        def fetch(query):
            calls.append(dict(query))
            self.assertNotIn('customer_email', query)  # Host privately injects its bound selector.
            self.assertEqual((query['site_id'], query['game_id']), ('266', '1327'))
            rows = 20 if len(calls) == 1 else 1
            return dict(status='partial', complete=False, semantics='live_non_snapshot',
                        data=[dict(order_id=str(n), customer_email='private@example.test', status='11', pay_status='1')
                              for n in range(rows)], next_cursor='opaque-first-window' if len(calls) == 1 else None)
        value = self.observe(fetch)
        self.assertEqual([(q['start'], q['end_exclusive'], q.get('cursor')) for q in calls],
                         [('2026-10-01', '2026-10-29', None),
                          ('2026-10-01', '2026-10-29', 'opaque-first-window'),
                          ('2026-10-29', '2026-10-30', None)])
        self.assertEqual((value['pages'], value['observed_order_rows']), (3, 22))
        self.assertEqual(value['status'], 'partial')
        self.assertFalse(value['complete'])
        self.assertIsNone(value['lifetime_first_paid_at'])
        self.assertEqual(value['source_states'], [{'status': '11', 'pay_status': '1', 'rows': 22}])
        for forbidden in ('private@example.test', 'opaque-first-window', 'order_id', 'goal_id'):
            self.assertNotIn(forbidden, json.dumps(value))

    def test_failed_or_revoked_later_page_and_exhausted_budget_never_return_zero_or_success(self):
        calls = []
        def fetch(query):
            calls.append(query)
            if len(calls) > 1:
                raise PermissionError('host_scope_revoked')
            return dict(status='partial', complete=False, semantics='live_non_snapshot',
                        data=[], next_cursor='next')
        with self.assertRaises(PermissionError):
            self.observe(fetch)
        calls.clear()
        with self.assertRaisesRegex(ValueError, 'page_budget_exhausted'):
            self.observe(fetch, max_pages=1)
        self.assertEqual(len(calls), 1)

    def test_window_boundary_is_live_only_and_metadata_only_rows_are_not_empty_customer_history(self):
        from unittest.mock import Mock
        fetch = Mock()
        with self.assertRaisesRegex(ValueError, 'live_date_boundary'):
            self.observe(fetch, start='2025-11-01', end_exclusive='2025-11-02')
        fetch.assert_not_called()
        fetch.return_value = dict(status='partial', complete=False, semantics='live_non_snapshot',
                                  data=[], observed_page_rows=20, next_cursor=None)
        with self.assertRaisesRegex(PermissionError, 'live_private_projection_required'):
            self.observe(fetch)


if __name__ == "__main__":
    unittest.main()
