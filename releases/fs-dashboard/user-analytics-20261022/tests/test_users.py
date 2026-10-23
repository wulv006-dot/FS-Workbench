"""Small deterministic contract cases T01–T24. Fixtures are invented, never business data."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from user_contract import TZ, aggregate_only, checked_query, stamp
from user_query import Service
from user_source import synchronize, windows
from user_store import Store
from user_tools import invoke, register_native, research_call
from user_http import get as http_get

BASE = Path(__file__).resolve().parents[1]
NOW = stamp('2026-10-22T12:00:00+08:00')


def order(n, paid, email='a@example.test', gid='1327', uid=0, site='266', status=1):
    return dict(id=n, order_no='test-' + str(n), paytime=paid, email=email, gid=gid, uid=uid, site_id=site, pay_status=status, status='11')


class Users(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = json.loads((BASE / 'source/user_config.json').read_text())
        self.store = Store(Path(self.tmp.name) / 'private', b'x' * 32, self.config)
        self.service = Service(self.store, lambda user, query, private: user == 'admin' or user == 'reader' and not private,
                               clock=lambda: NOW)

    def load(self, rows, start='2026-01-01', end='2026-10-22', site='266'):
        return self.store.replace_window(site, start, end, rows, NOW.isoformat())

    def query(self, start='2026-10-01', end='2026-10-22', **more):
        return self.service.query(dict(start=start, end_exclusive=end, **dict({'state_basis': 'period_end'}, **more)), 'admin')

    def values(self, value):
        return {k: v['value'] for k, v in value['metrics'].items()}

    def origins(self):
        self.config['history_origins'] = {'global:': '2026-01-01', 'project:1327': '2026-01-01', 'project:2000': '2026-01-01'}

    def test_T01_guest_and_member_exact_email(self):
        self.load([order(1, '2026-10-01 12:00:00'), order(2, '2026-10-02 12:00:00', uid=42)])
        self.assertEqual(self.values(self.query())['purchasers'], 1)
        self.assertEqual(len(self.store.read()[1]), 2)

    def test_current_pool_and_d0_do_not_move_with_interval(self):
        self.origins()
        self.load([order(1,'2026-01-03',email='old@example.test'),order(2,'2026-09-01',email='old@example.test'),
                   order(3,'2026-10-20',email='new@example.test'),order(4,'2026-03-01',email='sleep@example.test')])
        a=self.query(start='2026-08-01',state_basis='current')
        b=self.query(start='2026-10-01',state_basis='current')
        for key in ('known_pool','recent','silent','lost','long_lost'):
            self.assertEqual(a['metrics'][key],b['metrics'][key])
        self.assertEqual(a['observation_date'],'2026-10-22')
        old=self.service.query({'snapshot_id':a['snapshot_id']},'admin')
        self.assertEqual(old,a)
        rows=self.service.members(dict(snapshot_id=a['snapshot_id'],group='silent'),'admin')['rows']
        self.assertEqual(rows[0]['first_paid_at'],'2026-01-03T00:00:00+08:00')
        self.assertEqual(rows[0]['period_path'],'returned_then_inactive')
        self.assertEqual(self.service.members(dict(snapshot_id=b['snapshot_id'],group='silent__no_purchase'),'admin')['total'],1)
        private=self.service.detail(dict(snapshot_id=a['snapshot_id'],customer_id=rows[0]['customer_id']),'admin')
        self.assertEqual(private['timeline'][0]['days_from_d0'],0)
        self.assertIn('lost_return',{r['kind'] for r in private['timeline']})
        self.assertEqual(invoke(self.service,'reader',dict(snapshot_id=a['snapshot_id'],section='trajectories'))['trajectories'],a['trajectories'])

    def test_default_current_and_explicit_historical_are_distinct(self):
        self.load([order(1,'2026-01-03'),order(2,'2026-10-20')])
        current=self.service.query(dict(start='2026-02-01',end_exclusive='2026-03-01'),'admin')
        old=self.query(start='2026-02-01',end='2026-03-01')
        self.assertEqual(current['query']['state_basis'],'current')
        self.assertEqual(current['metrics']['recent']['value'],1)
        self.assertEqual(old['metrics']['silent']['value'],1)
        self.assertEqual(old['observation_date'],'2026-02-28')

    def test_after_period_observation_does_not_claim_true_first_purchase(self):
        self.load([order(1,'2026-10-20')])
        result=self.query(start='2026-02-01',end='2026-03-01',state_basis='current')
        rows=self.service.members(dict(snapshot_id=result['snapshot_id'],group='recent__observed_after_period'),'admin')['rows']
        self.assertEqual(len(rows),1)
        self.assertFalse(rows[0]['first_verified'])
        self.assertIsNone(rows[0]['first_paid_at'])

    def test_history_completion_requires_inventory_and_contiguous_coverage(self):
        from user_contract import digest
        self.load([order(1,'2026-01-03')])
        inventory={'fixture-month':1}
        (self.store.root/'history-full-inventory.json').write_text(json.dumps(inventory))
        proof=dict(contract='fs-users-available-source-history-v1',sites=['266'],start='2026-01-01',end_exclusive='2026-10-22',inventory_sha256=digest(inventory))
        path=self.store.root/'history-origin.json';path.write_text(json.dumps(proof))
        result=self.query(start='2026-01-01')
        self.assertEqual(result['metrics']['first_purchasers']['value'],1)
        proof['start']='2025-01-01';path.write_text(json.dumps(proof))
        self.service.cache.clear()
        with self.assertRaisesRegex(ValueError,'history_completion_proof'):
            self.query(start='2026-01-01')

    def test_history_months_are_bounded_and_finite(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('users_backfill_fixture',BASE/'backfill_history.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        windows=list(module.months(stamp('1970-03-14T12:00:00'),'1970-01-01'))
        self.assertEqual(len(windows),3)
        self.assertEqual(windows[-1][0],stamp('1970-01-01'))
        self.assertTrue(all((b-a).days<=31 and a<b for a,b in windows))
        self.assertEqual(list(module.months(stamp('1970-01-01'),'1970-01-01')),[])
        windows=list(module.months(NOW,'2026-07-01'))
        self.assertEqual(windows[-1][0],stamp('2026-07-01'))
        self.assertEqual(len(windows),4)

    def test_backfill_stops_at_user_bound_and_keeps_original_daily_work(self):
        from user_jobs import tick_windows
        self.load([order(1,'2026-07-01')],start='2026-07-01')
        reasons=[reason for _,_,_,reason in tick_windows(self.store,NOW)]
        self.assertNotIn('historical_backfill',reasons)
        self.assertEqual(reasons,['today_overlap','yesterday_reconciliation','historical_refund_reconciliation'])

    def test_bounded_coverage_is_not_proof_of_real_d0(self):
        from user_contract import digest
        self.load([order(1,'2026-07-01')],start='2026-07-01')
        inventory={'fixture':1};(self.store.root/'history-full-inventory.json').write_text(json.dumps(inventory))
        proof=dict(contract='fs-users-bounded-history-v1',start='2026-07-01T00:00:00+08:00',end_exclusive='2026-10-22T00:00:00+08:00',sites=['266'],inventory_sha256=digest(inventory))
        (self.store.root/'history-coverage.json').write_text(json.dumps(proof))
        result=self.query(start='2026-07-01')
        self.assertTrue(result['coverage']['history_window']['complete'])
        self.assertIsNone(result['coverage']['historical_origin'])
        self.assertEqual(result['metrics']['first_purchasers']['status'],'insufficient_history')
        row=self.service.members(dict(snapshot_id=result['snapshot_id'],group='known_pool'),'admin')['rows'][0]
        detail=self.service.detail(dict(snapshot_id=result['snapshot_id'],customer_id=row['customer_id']),'admin')
        self.assertEqual(detail['timeline'][0]['days_from_observed_first'],0)
        self.assertIsNone(detail['timeline'][0]['days_from_d0'])

    def test_verified_legacy_complaint_status_keeps_payment_projection(self):
        paid=order(1,'2026-09-12');paid['status']='53'
        refunded=order(2,'2026-09-12',status=2);refunded['status']='53'
        self.load([paid,refunded])
        self.assertEqual(self.query(start='2026-09-01')['metrics']['purchasers']['value'],1)
        self.assertEqual([r['valid'] for r in self.store.read()[1]],[1,0])

    def test_reviewed_source_status_dictionary_cannot_change_exclusions(self):
        from user_runtime import configuration
        accounting=Path(self.tmp.name)/'accounting.json'
        accounting.write_text(json.dumps(dict(contract='channel-zero-cost-v1',testOrders={})));accounting.chmod(0o600)
        statuses=Path(self.tmp.name)/'statuses.json'
        proof=dict(contract='fs-users-reviewed-order-status-v1',statuses={'32':dict(label='fixture source status',classification='existing_payment_projection_unchanged',observed_rows=1,source_sha256='a'*64)})
        statuses.write_text(json.dumps(proof));statuses.chmod(0o600)
        config=configuration(BASE/'source/user_config.json',accounting,statuses)
        self.assertIn('32',config['known_order_statuses'])
        self.assertEqual(config['excluded_order_statuses'],self.config['excluded_order_statuses'])
        self.assertEqual(len(config['source_status_rule_sha256']),64)
        proof['statuses']['32']['classification']='include_refunds';statuses.write_text(json.dumps(proof))
        with self.assertRaisesRegex(ValueError,'status_evidence'):
            configuration(BASE/'source/user_config.json',accounting,statuses)

    def test_unknown_source_status_stops_and_preserves_minimal_private_capture(self):
        from user_source import shared_sync
        from types import SimpleNamespace
        raw=order(1,'2026-09-01');raw.update(status='999',status_format='fixture unknown',address='must not persist')
        session=SimpleNamespace(bind_admin_token=lambda _:None,close=lambda:None)
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fixture',None))
        channel=SimpleNamespace(pages=lambda *args:[raw])
        with patch.dict('sys.modules',{'p2pah_auth':auth,'channel_source':channel}):
            with self.assertRaisesRegex(RuntimeError,'unmapped_order_status'):
                shared_sync(self.store,'266','2026-09-01','2026-09-02')
        saved=list(self.store.root.glob('source-review-*.json'));self.assertEqual(len(saved),1)
        capture=json.loads(saved[0].read_text())
        self.assertEqual(capture['rows'][0]['status'],'999')
        self.assertNotIn('address',capture['rows'][0])
        self.assertEqual(saved[0].stat().st_mode&0o077,0)
        self.assertEqual(self.store.read()[1],[])

    def test_sweep_matches_daily_reference_at_boundaries_and_gaps(self):
        from user_lifecycle import daily_stocks
        from user_contract import state,STATES
        people={'a':[dict(paid_at=t) for t in ('2026-01-01','2026-01-31','2026-03-01T12:00:00')],
                'b':[dict(paid_at=t) for t in ('2026-01-01T12:00:00','2026-02-10T12:00:00')]}
        runs={'266':[(stamp('2026-01-01'),stamp('2026-02-15')),(stamp('2026-03-01'),stamp('2026-05-01'))]}
        start,end=stamp('2026-01-01'),stamp('2026-04-02T12:00:00')
        stocks=daily_stocks(people,runs,start,end,(30,60,90))
        for day,actual in stocks.items():
            finish=min(datetime.combine(day+timedelta(days=1),datetime.min.time(),TZ),end)
            expected={key:0 for key in (*STATES,'unverified')}
            for rows in people.values():
                times=[stamp(r['paid_at']) for r in rows if stamp(r['paid_at'])<finish]
                if times:
                    last=max(times)
                    key=state(last,(finish-timedelta(microseconds=1)).date(),(30,60,90)) if any(a<=last and finish<=b for a,b in runs['266']) else 'unverified'
                    expected[key]+=1
            self.assertEqual(actual,expected,day)

    def test_daily_transition_records_once_per_day_without_source(self):
        from user_jobs import advance_day
        self.load([order(1, '2026-09-22 12:00:00')], end='2026-10-24')
        revision = self.store.revision()
        first = advance_day(self.store, NOW)
        advance_day(self.store, NOW + timedelta(hours=1))
        second = advance_day(self.store, NOW + timedelta(days=1))
        records = (self.store.root / 'daily-transitions.jsonl').read_text().splitlines()
        self.assertEqual(len(records), 2)
        self.assertEqual(first['stocks']['recent']['value'], 1)
        self.assertEqual(second['stocks']['silent']['value'], 1)
        self.assertEqual(self.store.revision(), revision)
        self.assertFalse(second['source_collection'])

    def test_daily_origin_on_systemd_without_invocation_id(self):
        from user_jobs import advance_day
        with patch.dict('os.environ', {}, clear=True):
            self.assertEqual(advance_day(self.store, NOW)['trigger'], 'manual')
        with patch.dict('os.environ', {'FS_USER_ANALYTICS_TRIGGER': 'systemd'}, clear=True):
            result = advance_day(self.store, NOW)
        self.assertEqual(result['trigger'], 'systemd')
        self.assertIsNone(result['invocation_id'])
        unit = (BASE / 'deploy/fs-user-analytics.service').read_text()
        self.assertIn('Environment=FS_USER_ANALYTICS_TRIGGER=systemd', unit)
        self.assertIn('ProtectSystem=full', unit)
        self.assertIn('ReadWriteDirectories=', unit)
        self.assertNotIn('ReadWritePaths=', unit)

    def test_natural_receipt_requires_unchanged_last_purchase_and_actual_stage_change(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('users_natural_receipt_test', BASE / 'accept_natural.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        before = {'a': dict(last_paid_at='2026-09-23T12:00:00+08:00', stage='recent')}
        after = {'a': dict(last_paid_at='2026-09-23T12:00:00+08:00', stage='silent')}
        old, new = stamp('2026-10-22').date(), stamp('2026-10-23').date()
        self.assertEqual(len(module.transition_sample(before, after, old, new, [30, 60, 90])), 1)
        after['a'].update(last_paid_at='2026-10-23T12:00:00+08:00', stage='recent')
        self.assertEqual(module.transition_sample(before, after, old, new, [30, 60, 90]), [])
        after['a'].update(last_paid_at=before['a']['last_paid_at'], stage='lost')
        with self.assertRaises(AssertionError):module.transition_sample(before, after, old, new, [30, 60, 90])

    def test_T02_cross_project_union(self):
        self.load([order(1, '2026-10-01'), order(2, '2026-10-02', gid='2000')])
        self.assertEqual(self.values(self.query())['purchasers'], 1)
        for gid in ('1327', '2000'):
            self.assertEqual(self.values(self.query(scope='project', scope_id=gid))['purchasers'], 1)

    def test_tool_project_rules_are_frozen_separately_from_summary(self):
        self.load([order(1, '2026-10-01')])
        frozen = self.query()
        self.config['policies']['fc-v1'] = [1, 2, 3]
        result = invoke(self.service, 'admin', dict(snapshot_id=frozen['snapshot_id']))
        self.assertEqual(result['lifecycle_policy']['thresholds_days'], [30, 60, 90])
        self.assertEqual(result['project_policy_versions']['1327'], 'fc-v1')
        self.assertEqual(result['lifecycle_policies']['fc-v1'], [14, 30, 90])
        self.assertIn('code', result['source_status_codes']['order_status']['86'])

    def test_T03_cross_site_requires_verified_semantics(self):
        self.config['sites']['777'] = dict(label='fixture satellite', verified_identity_group=None)
        self.load([order(1, '2026-10-01')])
        self.load([order(2, '2026-10-02', site='777')], site='777')
        result = self.query()
        self.assertIsNone(result['metrics']['purchasers']['value'])
        self.assertEqual(self.values(self.query(scope='site', scope_id='266'))['purchasers'], 1)

    def test_T04_project_first_company_old(self):
        self.origins()
        self.load([order(1, '2026-09-01'), order(2, '2026-10-02', gid='2000')])
        result = self.query(view='projects')
        project = next(p for p in result['projects'] if p['project_id'] == '2000')
        self.assertEqual(project['acquisition'], dict(global_first=0, existing_global=1, global_unknown=0))

    def test_T05_first_seen_is_unknown(self):
        self.load([order(1, '2026-10-02')], start='2026-10-01')
        value = self.values(self.query())
        self.assertEqual((value['first_purchasers'], value['old_purchasers'], value['first_unverified']), (0, 0, 1))

    def test_T06_known_old_without_lifetime_first(self):
        self.load([order(1, '2026-09-01'), order(2, '2026-10-02')], start='2026-09-01')
        self.assertEqual(self.values(self.query())['old_purchasers'], 1)

    def test_T07_period_not_sum_of_daily(self):
        self.load([order(1, '2026-10-01'), order(2, '2026-10-02')])
        result = self.query()
        self.assertEqual(sum(r['purchasers'] for r in result['trend']), 2)
        self.assertEqual(self.values(result)['purchasers'], 1)

    def test_T08_half_open_midnight(self):
        self.load([order(1, '2026-10-01 00:00:00'), order(2, '2026-10-22 00:00:00', email='b@example.test')], end='2026-10-23')
        result = self.query()
        self.assertEqual(self.values(result)['purchasers'], 1)
        self.assertEqual(result['observation_date'], '2026-10-21')

    def test_T09_exact_fc_thresholds(self):
        for days, wanted in ((13, 'recent'), (14, 'silent'), (29, 'silent'), (30, 'lost'), (89, 'lost'), (90, 'long_lost')):
            with self.subTest(days=days):
                paid = (stamp('2026-10-21') - timedelta(days=days)).isoformat()
                self.load([order(1, paid)])
                result = self.values(self.query(scope='project', scope_id='1327'))
                self.assertEqual(result[wanted], 1)

    def test_T10_no_order_next_day_progresses(self):
        self.load([order(1, '2026-10-01')])
        a = self.values(self.query(end='2026-10-15', scope='project', scope_id='1327'))
        b = self.values(self.query(end='2026-10-16', scope='project', scope_id='1327'))
        self.assertEqual((a['recent'], b['silent']), (1, 1))
        self.assertEqual(a['entered_silent'], 0)
        self.assertEqual(b['entered_silent'], 1)

    def test_T11_threshold_purchase_midnight_vs_noon(self):
        for hour, enters in (('00:00:00', 0), ('12:00:00', 1)):
            with self.subTest(hour=hour):
                self.load([order(1, '2026-10-01'), order(2, '2026-10-15 ' + hour)])
                result = self.values(self.query(end='2026-10-16', scope='project', scope_id='1327'))
                self.assertEqual((result['entered_silent'], result['silent_wakeup'], result['recent']), (enters, enters, 1))

    def test_T12_multiple_entries_unique_people(self):
        self.load([order(1, '2026-09-01'), order(2, '2026-09-16')])
        result = self.query(start='2026-09-01', scope='project', scope_id='1327')
        self.assertEqual(result['metrics']['entered_silent']['value'], 1)
        self.assertEqual(result['metrics']['entered_silent']['events'], 2)

    def test_T13_future_purchase_does_not_change_past(self):
        self.load([order(1, '2026-09-01'), order(2, '2026-10-20')])
        result = self.values(self.query(start='2026-09-01', end='2026-10-01', scope='project', scope_id='1327'))
        self.assertEqual((result['silent'], result['recent']), (1, 0))

    def test_T14_refund_recalculates_and_keeps_old_snapshot(self):
        rows = [order(1, '2026-09-01'), order(2, '2026-10-20')]
        self.load(rows)
        old = self.query(scope='project', scope_id='1327')
        rows[1]['pay_status'] = 2
        self.load(rows)
        new = self.query(scope='project', scope_id='1327')
        self.assertEqual((self.values(old)['recent'], self.values(new)['lost']), (1, 1))
        self.assertEqual(self.service.query({'snapshot_id': old['snapshot_id']}, 'admin'), old)
        self.load([dict(r, pay_status=2) for r in rows])
        self.assertEqual(self.values(self.query())['known_pool'], 0)

    def test_T15_refund_coverage_is_not_claimed_global(self):
        self.load([order(1, '2026-09-01')])
        self.load([], start='2026-10-01')
        self.assertEqual(self.query()['coverage']['refund_correction'], 'only_reenumerated_payment_windows')

    def test_T16_duplicate_or_failed_window_is_atomic(self):
        one = order(1, '2026-10-01')
        self.load([one]); self.load([one])
        self.assertEqual(len(self.store.read()[1]), 1)
        previous = self.store.read()[0]
        with self.assertRaisesRegex(ValueError, 'duplicate_order'):
            self.load([one, one])
        self.assertEqual(self.store.read()[0], previous)
        self.assertEqual(self.values(self.query())['known_pool'], 1)

    def test_T17_failed_enumeration_never_becomes_zero(self):
        self.load([order(1, '2026-10-01')])
        def broken(*args):
            raise ValueError('admin_pagination_changed')
        with self.assertRaises(RuntimeError):
            synchronize(self.store, '266', '2026-10-01', '2026-10-22', None, broken)
        self.assertEqual(self.values(self.query())['purchasers'], 1)
        self.assertIn('failed', {j['state'] for j in self.store.read()[2]})

    def test_T18_missing_identity_and_recent_coverage_gap(self):
        self.load([order(1, '2026-10-01'), order(2, '2026-10-02', email=None)], end='2026-10-03')
        result = self.query()
        self.assertEqual(result['coverage']['missing_identity_orders'], 1)
        self.assertEqual(self.values(result)['unverified'], 1)
        self.assertEqual(self.values(result)['long_lost'], 0)

    def test_T19_cohort_maturity_and_null_denominator(self):
        self.origins()
        self.load([order(1, '2026-10-20')])
        self.assertIsNone(self.query()['cohort']['rate'])
        self.load([order(1, '2026-10-01')])
        self.assertEqual(self.query()['cohort']['rate'], 0)
        self.assertEqual(self.query()['cohort']['denominator'], 1)

    def test_T20_same_second_and_exclusive_second_purchase_end(self):
        self.origins()
        for paid, expected in (('2026-10-01 12:00:00', 1), ('2026-10-08 12:00:00', 0)):
            self.load([order(1, '2026-10-01 12:00:00'), order(2, paid)])
            self.assertEqual(self.query()['cohort']['numerator'], expected)

    def test_T21_project_lost_company_recent(self):
        self.load([order(1, '2026-09-01'), order(2, '2026-10-20', gid='2000')])
        result = self.query(view='migration')
        flow = next(r for r in result['migration'] if r['project_id'] == '1327')
        self.assertIn(dict(project_stage='lost', global_stage='recent', count=1), flow['states'])
        self.assertTrue(flow['destinations_overlap'])

    def test_T22_new_policy_keeps_old_evidence(self):
        self.load([order(1, '2026-10-01')])
        old = self.query(scope='project', scope_id='1327')
        new = self.query(scope='project', scope_id='1327', policy_version='common-v1')
        self.assertNotEqual(old['snapshot_id'], new['snapshot_id'])
        self.assertEqual(self.values(old)['silent'], 1)
        self.assertEqual(self.values(new)['recent'], 1)

    def test_T23_snapshot_card_drill_export_and_tools_agree(self):
        self.load([order(1, '2026-10-01')])
        result = self.query()
        args = dict(snapshot_id=result['snapshot_id'], group='purchasers')
        detail = self.service.members(args, 'admin')
        exported = self.service.export(args, 'admin')
        self.assertEqual(detail['total'], self.values(result)['purchasers'])
        self.assertEqual(detail['rows'], exported['rows'])
        projected = research_call(self.service, 'admin', {'snapshot_id': result['snapshot_id']})
        for key in ('snapshot_id', 'evidence_id', 'metrics', 'query', 'coverage'):
            self.assertEqual(projected[key], result[key])
        self.assertEqual(projected['source_window_counts'],dict(complete=1,failed=0))
        self.assertEqual(projected['source_coverage'],[dict(site='266',start=result['source_watermark'][0]['start'],end_exclusive=result['source_watermark'][0]['end_exclusive'])])
        self.assertNotIn('projects', projected)
        class Context:
            def register_tool(context, **kwargs):
                context.handler = kwargs['handler']
        ctx = Context()
        register_native(ctx, self.service, 'admin')
        self.assertEqual(json.loads(ctx.handler({'snapshot_id': result['snapshot_id']})), projected)
        with self.assertRaises(LookupError):
            self.service.query({'snapshot_id': 'us_' + '0' * 32}, 'admin')

    def test_T24_permissions_scope_and_aggregate_identity(self):
        self.load([order(1, '2026-10-01')])
        result = self.query()
        aggregate_only(result)
        for user in ('reader', '', 'expired'):
            with self.assertRaises(PermissionError):
                self.service.members(dict(snapshot_id=result['snapshot_id'], group='purchasers'), user)
        with self.assertRaises(ValueError):
            self.query(scope='site', scope_id='999')
        with self.assertRaises(ValueError):
            invoke(self.service, 'admin', {'email': 'a@example.test'})
        self.assertNotIn('a@example.test', json.dumps(result))

    def test_key_or_identity_mapping_change_requires_migration(self):
        with self.assertRaises(ValueError):
            Store(self.store.root, b'y' * 32, self.config)

    def test_window_splits_and_today_as_of(self):
        self.assertEqual(len(list(windows('2026-09-01', '2026-10-22'))), 2)
        query = checked_query(dict(start='2026-10-22', end_exclusive='2026-10-23'), self.config, NOW)
        self.assertEqual(query['as_of'], NOW.isoformat())
        with self.assertRaises(ValueError):
            checked_query(dict(start='2026-10-01', end_exclusive='2026-10-20', as_of='2026-10-19'), self.config, NOW)

    def test_verified_cross_site_union(self):
        config = copy.deepcopy(self.config)
        config['sites'] = {sid: dict(label=sid, verified_identity_group='verified-fixture-primary-email') for sid in ('266', '777')}
        store = Store(Path(self.tmp.name) / 'verified-sites', b'z' * 32, config)
        for sid in ('266', '777'):
            store.replace_window(sid, '2026-01-01', '2026-10-22', [order(1, '2026-10-01', site=sid)], NOW.isoformat())
        service = Service(store, lambda *args: True, clock=lambda: NOW)
        result = service.query(dict(start='2026-10-01', end_exclusive='2026-10-22'), 'fixture-admin')
        self.assertEqual(result['metrics']['purchasers']['value'], 1)

    def test_email_local_part_preserved(self):
        self.load([order(1, '2026-10-01', email='A@example.test'), order(2, '2026-10-01', email='a@example.test'),
                   order(3, '2026-10-01', email='a+tag@example.test')])
        self.assertEqual(self.values(self.query())['purchasers'], 3)

    def test_http_auth_and_duplicate_query_rejected(self):
        self.assertEqual(http_get(self.service, '/users', {}, '')[0], 401)
        self.assertEqual(http_get(self.service, '/users', {'start': ['a', 'b']}, 'admin')[0], 422)
        self.assertEqual(http_get(None, '/users', {}, 'admin')[0], 503)
        self.load([order(1, '2026-10-01')])
        result = self.query()
        params = {'snapshot_id': [result['snapshot_id']], 'group': ['purchasers']}
        self.assertEqual(http_get(self.service, '/users/private', params, 'reader')[0], 403)

    def test_scope_permission_does_not_grant_global_migration(self):
        self.load([order(1, '2026-10-01')])
        restricted = Service(self.store, lambda user, q, p: q['scope'] == 'project', clock=lambda: NOW)
        args = dict(start='2026-10-01', end_exclusive='2026-10-22', scope='project', scope_id='1327')
        self.assertEqual(restricted.query(args, 'project-reader')['metrics']['purchasers']['value'], 1)
        with self.assertRaises(PermissionError):
            restricted.query(dict(args, view='migration'), 'project-reader')

    def test_frozen_query_mismatch_never_switches_scope(self):
        self.load([order(1, '2026-10-01')])
        old = self.query()
        with self.assertRaises(ValueError):
            self.service.query(dict(old['query'], scope='site', scope_id='266', snapshot_id=old['snapshot_id']), 'admin')

    def test_partial_frozen_query_checks_only_supplied_conditions(self):
        self.load([order(1, '2026-10-01')])
        old = self.query()
        for args in ({'view': 'summary'}, {'start': '2026-10-01'}, {'H': 7}):
            self.assertEqual(self.service.query(dict(snapshot_id=old['snapshot_id'], **args), 'admin'), old)
        for args in ({'scope': 'site'}, {'start': '2026-10-02'}, {'H': True}, {'view': 'trend'}, {'extra': 'x'}):
            with self.assertRaises(ValueError):
                self.service.query(dict(snapshot_id=old['snapshot_id'], **args), 'admin')

    def test_compact_tool_retains_large_sections_under_same_snapshot(self):
        self.load([order(1, '2026-10-01')])
        old = self.query();query, public, private = self.store.snapshot(old['snapshot_id'])
        public = {k: v for k, v in public.items() if k not in ('snapshot_id', 'evidence_id')}
        public['projects'] = [{'project_id': str(i), 'policy_version': 'common-v1', 'label': 'fixture project ' + 'x' * 2048} for i in range(100)]
        full = self.store.save_snapshot(query, public, private)
        summary = invoke(self.service, 'admin', {'snapshot_id': full['snapshot_id'], 'view': 'summary'})
        self.assertLess(len(json.dumps(summary)), 20000)
        self.assertEqual(summary['lifecycle_policy']['thresholds_days'], [30, 60, 90])
        self.assertIn('does not set lifecycle', summary['interpretation']['H'])
        self.assertEqual(summary['metric_definitions']['high_value_entered_silent']['label'], '高价值且刚进入沉默')
        for key in ('snapshot_id', 'evidence_id', 'metrics', 'query', 'coverage'):
            self.assertEqual(summary[key], full[key])
        projects = invoke(self.service, 'admin', {'snapshot_id': full['snapshot_id'], 'section': 'projects'})
        self.assertEqual(projects['projects'], full['projects'])
        self.assertEqual(projects['snapshot_id'], summary['snapshot_id'])
        self.assertEqual(self.service.query({'snapshot_id': full['snapshot_id']}, 'admin'), full)

    def test_tool_compacts_many_source_windows_without_filling_gaps(self):
        self.load([order(1,'2026-10-01')])
        frozen=self.query();query,public,private=self.store.snapshot(frozen['snapshot_id'])
        public={k:v for k,v in public.items() if k not in ('snapshot_id','evidence_id')}
        start=stamp('2000-01-01')
        public['source_watermark']=[dict(site='266',start=(start+timedelta(days=i)).isoformat(),end_exclusive=(start+timedelta(days=i+1)).isoformat(),state='complete') for i in range(3000) if i!=1500]
        public['source_watermark'].append(dict(site='266',start=(start+timedelta(days=1500)).isoformat(),end_exclusive=(start+timedelta(days=1501)).isoformat(),state='failed'))
        frozen=self.store.save_snapshot(query,public,private)
        result=invoke(self.service,'admin',dict(snapshot_id=frozen['snapshot_id']))
        self.assertLess(len(json.dumps(result)),20000)
        self.assertEqual(len(result['source_coverage']),2)
        self.assertEqual(result['source_window_counts'],dict(complete=2999,failed=1))
        self.assertEqual(result['source_coverage'][0]['end_exclusive'],(start+timedelta(days=1500)).isoformat())

    def test_custom_policy_is_frozen_independently_from_cohort_horizon(self):
        self.config['policies']['fixture-v2'] = [20, 40, 80]
        self.load([order(1, '2026-10-01')])
        old = self.query(policy_version='fixture-v2', H=7)
        self.config['policies']['fixture-v2'] = [21, 41, 81]
        value = invoke(self.service, 'admin', {'snapshot_id': old['snapshot_id']})
        self.assertEqual(value['lifecycle_policy']['thresholds_days'], [20, 40, 80])
        self.assertEqual(value['query']['H'], 7)

    def test_required_count_partitions_and_tombstones(self):
        self.origins()
        self.load([order(1, '2026-09-01', email='old@example.test'), order(2, '2026-10-01', email='old@example.test'),
                   order(3, '2026-10-01', email='new@example.test')])
        values = self.values(self.query())
        self.assertEqual(values['purchasers'], sum(values[k] for k in ('first_purchasers', 'old_purchasers', 'first_unverified')))
        self.assertEqual(values['known_pool'], sum(values[k] for k in ('recent', 'silent', 'lost', 'long_lost', 'unverified')))
        self.load([], start='2026-10-01')
        self.assertEqual(self.values(self.query())['purchasers'], 0)

    def test_live_status_projection_and_exact_test_identity(self):
        rows = [dict(order(1, '2026-10-01'), status='22', amount_usd_format='$12.00'),
                dict(order(2, '2026-10-02'), status='80', amount_usd_format='$0.00'),
                dict(order(3, '2026-10-03', status=2), status='86', amount_usd_format='$15.00')]
        self.load(rows)
        self.assertEqual(self.values(self.query())['purchasers'], 1)
        facts = self.store.read()[1]
        self.assertEqual([r['valid'] for r in facts], [0, 1, 0])
        self.assertEqual(json.loads(facts[1]['body'])['amount_usd'], '0')
        self.config['verified_test_rules'] = {'test-2': {'gid': '1327', 'salesUsd': '0.00'}}
        self.load(rows)
        self.assertEqual(self.values(self.query())['purchasers'], 0)
        self.config['verified_test_rules']['test-2']['gid'] = '1329'
        with self.assertRaisesRegex(ValueError, 'test_order_identity_mismatch'):
            self.load(rows)

    def test_unmapped_status_does_not_publish_coverage(self):
        with self.assertRaisesRegex(ValueError, 'unmapped_order_status'):
            self.load([dict(order(1, '2026-10-01'), status='unverified-status')])
        self.assertEqual(self.store.revision(), '0')
        result = self.query()
        self.assertIsNone(result['metrics']['purchasers']['value'])
        self.assertEqual(result['metrics']['purchasers']['status'], 'pending')

    def test_private_detail_is_frozen_and_admin_only(self):
        self.load([dict(order(1, '2026-10-01'), amount_usd_format='$12.50')])
        result = self.query()
        member = self.service.members(dict(snapshot_id=result['snapshot_id'], group='purchasers'), 'admin')['rows'][0]
        args = dict(snapshot_id=result['snapshot_id'], customer_id=member['customer_id'])
        with self.assertRaises(PermissionError):
            self.service.detail(args, 'reader')
        self.load([order(1, '2026-10-01', status=2)])
        detail = self.service.detail(args, 'admin')
        self.assertEqual(detail['email'], 'a@example.test')
        self.assertEqual(detail['orders'][0]['pay_status'], 1)
        from decimal import Decimal
        self.assertEqual(Decimal(detail['customer']['period_sales_usd']), Decimal('12.50'))

    def test_cached_summary_does_not_retain_revoked_global_permission(self):
        self.load([order(1, '2026-10-01')])
        allowed = [True]
        service = Service(self.store, lambda u, q, p: allowed[0] or q['scope'] == 'project', clock=lambda: NOW)
        args = dict(start='2026-10-01', end_exclusive='2026-10-22', scope='project', scope_id='1327')
        self.assertIn('projects', service.query(args, 'same-user'))
        allowed[0] = False
        self.assertNotIn('projects', service.query(args, 'same-user'))

    def test_backup_retains_identity_and_snapshot(self):
        import sqlite3
        self.load([order(1, '2026-10-01')])
        result = self.query()
        destination = Path(self.tmp.name) / 'backup.sqlite3'
        self.store.backup(destination)
        with sqlite3.connect(destination) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT count(*) FROM identities').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT id FROM snapshots').fetchone()[0], result['snapshot_id'])
        with self.assertRaises(FileExistsError):
            self.store.backup(destination)

    def test_frozen_snapshot_rechecks_global_context_permission(self):
        self.load([order(1, '2026-10-01')])
        allowed = [True]
        service = Service(self.store, lambda u, q, p: allowed[0] or q['scope'] == 'project', clock=lambda: NOW)
        frozen = service.query(dict(start='2026-10-01', end_exclusive='2026-10-22', scope='project', scope_id='1327'), 'same-user')
        allowed[0] = False
        with self.assertRaises(PermissionError):
            service.query(dict(snapshot_id=frozen['snapshot_id']), 'same-user')

    def test_daily_planning_busy_source_and_identity_backup(self):
        import fcntl
        from user_jobs import day_windows, has_window, synchronize_day, backup
        from user_runtime import load_store
        self.assertEqual(len(list(day_windows('2026-10-01', '2026-10-03'))), 2)
        with self.assertRaises(ValueError):
            list(day_windows('2026-10-01T12:00:00', '2026-10-03'))
        self.load([order(1, '2026-10-01')])
        self.assertTrue(has_window(self.store.read()[2], '266', '2026-10-01', '2026-10-02'))
        lock_path = Path(self.tmp.name) / 'existing-source.lock'
        with lock_path.open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = synchronize_day(self.store, '266', '2026-10-01', '2026-10-02', reader=lambda *_: self.fail('busy source must not be called'), lock_path=lock_path)
            self.assertEqual(result['status'], 'deferred')
        root = Path(self.tmp.name) / 'new-private-root'
        store = load_store(root, self.config)
        same = load_store(root, self.config)
        self.assertEqual(store.key, same.key)
        manifest = backup(store, NOW)
        self.assertEqual(backup(store, NOW), manifest)
        (root / 'backups' / NOW.date().isoformat() / 'identity.key').write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError, 'backup_readback_mismatch'):
            backup(store, NOW)

    def test_project_mapping_migration_preserves_customer_and_old_snapshot(self):
        self.load([order(1, '2026-10-01')])
        old = self.query()
        cid = self.store.read()[1][0]['customer_id']
        updated = copy.deepcopy(self.config)
        updated['scope_version'] += '-next-fixture'
        updated['projects']['2000'] = dict(label='Fixture project', series='Fixture series')
        self.store.remap_projects(updated)
        self.assertEqual(self.store.read()[1][0]['customer_id'], cid)
        self.assertEqual(self.service.query(dict(snapshot_id=old['snapshot_id']), 'admin'), old)
        self.assertEqual(Store(self.store.root, self.store.key, updated).revision(), self.store.revision())
        denied = copy.deepcopy(updated)
        denied['scope_version'] += '-denied'
        denied['sites']['266']['verified_identity_group'] = 'unverified-change'
        with self.assertRaisesRegex(ValueError, 'explicit_identity_migration_required'):
            self.store.remap_projects(denied)

    def test_weekly_cohort_uses_same_observation_cutoff(self):
        self.origins()
        self.load([order(1, '2026-10-01'), order(2, '2026-10-05'), order(3, '2026-10-10', email='b@example.test'), order(4, '2026-10-20', email='c@example.test')])
        result = self.query()
        self.assertEqual(sum(w['denominator'] for w in result['cohort_weeks']), result['cohort']['denominator'])
        self.assertEqual(sum(w['numerator'] for w in result['cohort_weeks']), 1)
        self.assertEqual(sum(w['observing'] for w in result['cohort_weeks']), 1)
        self.assertEqual(checked_query(dict(start='2026-10-01', end_exclusive='2026-10-22', scope='project', scope_id='833'), self.config, NOW)['policy_version'], 'fc-v1')

    def test_failed_recheck_keeps_good_watermark_and_failure_attempt(self):
        self.load([order(1, '2026-10-01')])
        self.store.failed_window('266', '2026-01-01', '2026-10-22', 'admin_page_failed')
        self.assertEqual(self.store.coverage()[0]['state'], 'complete')
        self.assertEqual(self.store.job_health()['failed_attempts'], 1)
        self.assertEqual(self.store.job_health()['latest_attempt']['state'], 'failed')


if __name__ == '__main__':
    unittest.main()
