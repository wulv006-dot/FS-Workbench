from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'source'))
from fc_pricing_v3 import api, scheduler, weekly_ladder as ladder
from fc_pricing_v3.curve_strategy_v6 import margin_band_parameters, market_anchor_parameters
from fc_pricing_v3.ledger import Ledger

NOW = datetime.fromisoformat('2026-11-23T01:00:00+08:00')


def weeks(now=NOW):
    result = []
    monday = now.date()
    for age in (14, 7):
        start = monday-timedelta(days=age)
        result.append(dict(start=start.isoformat(), end=(start+timedelta(days=6)).isoformat(), complete=True, publication_id='pin',
            days=[(start+timedelta(days=i)).isoformat() for i in range(7)], source_revision='actual-week-'+str(age),
            platforms={p:{b:dict(orders=100, merchandise_usd='1000', revenue_cny='6000', procurement_gross_cny='1200')
                          for b in ('small','large')} for p in ('PS','XBOX','PC')}))
    return result


class WeeklyLadder(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.db=Ledger(Path(folder.name)/'control.sqlite3')
        self.db.put('metadata','generation',{'id':'generation'})
        self.plan=dict(plan_id='plan',revision=4,generation='generation',actor='owner',state='ACTIVE',mode='smart',
            write_protocol='fc27_curve_v6',smart_strategy_version='market-anchor-v1',ends_at=None,
            resources=['base:'+p for p in ('PS','XBOX','PC')],starts_at=(NOW-timedelta(hours=2)).isoformat(),
            smart_started_at=(NOW-timedelta(hours=2)).isoformat(),last_cycle_at=NOW.isoformat(),
            parameters={'market_anchor':market_anchor_parameters()})
        self.db.put('pricing_plans','plan',self.plan)
        with self.db.transaction() as conn:
            for resource in self.plan['resources']:
                conn.execute('INSERT INTO plan_ownership VALUES (?,?,?,?)',(resource,'plan',4,'generation'))
        clock=patch('fc_pricing_v3.ledger.clock',return_value=NOW);clock.start();self.addCleanup(clock.stop)
        policy=patch('automation_policy.load_policy',return_value={'interval_minutes':60});policy.start();self.addCleanup(policy.stop)

    def run_week(self, now=NOW):
        a,b=weeks(now)
        self.db.put('metadata','latest_snapshot:plan',{'snapshot_id':'snapshot'})
        self.db.put('strategy_decisions','snapshot',dict(curve=[dict(platform=p,selection=dict(source='market_anchor',
            market_anchor=dict(parameters=market_anchor_parameters()[p],reference_usd_per_100k={'Lootbar':'10','U7Buy':'12'})))
            for p in ('PS','XBOX','PC')]))
        bridge=SimpleNamespace(review=Mock(return_value={'phase':'completed'}))
        with patch('fc_pricing_v3.average_discount_v6.yesterday_es_ready',return_value=True), \
             patch.object(ladder,'read_week',side_effect=[b,a]) as source, \
             patch.dict(sys.modules,{'hermes_pricing_bridge':bridge}):
            first=ladder.run(self.db,'plan',now)
            second=ladder.run(self.db,'plan',now+timedelta(hours=1))
        self.assertEqual(first,second)
        self.assertEqual(source.call_count,2)
        bridge.review.assert_called_once()
        return self.db.all('ladder_proposals')

    def test_auto_waits_for_owner_if_either_comparison_week_includes_promotion(self):
        anchors = market_anchor_parameters()
        for bands in anchors.values():
            for terms in bands.values():
                terms['p_low'] = '-.10'
        guard = dict(campaign='carnival_202611', start_day='2026-11-19', last_redeem_day='2026-11-22',
                     baseline={'PS': '.05', 'XBOX': '.07', 'PC': '.09'}, baseline_revision='se_' + 'a' * 32)
        margin = {p: {'target': '.31'} for p in ('PS', 'XBOX', 'PC')}
        self.plan['parameters'] = dict(market_anchor=anchors,
            margin_band=margin_band_parameters(dict(margin, promotion_guard=guard), anchors))
        self.db.put('pricing_plans', 'plan', self.plan)
        control = dict(automatic=True, eligible_after=(NOW - timedelta(days=1)).isoformat())
        self.db.put('metadata', 'weekly-ladder-control:plan', control)

        for offset in (0, 1, 2):
            now = NOW + timedelta(weeks=offset)
            rows = [row for row in self.run_week(now) if row['week_start'] == now.date().isoformat()]
            self.assertEqual(len(rows), 3)
            self.assertEqual({row['procurement_gross_cny'] for row in rows}, {'2400'})
            self.assertEqual({row['status'] for row in rows}, {'PROPOSED' if offset < 2 else 'CONFIRMED'})
            self.assertEqual(self.db.get('metadata', 'weekly-ladder-control:plan'), control)
            if offset == 0:
                row = next(row for row in rows if row['platform'] == 'PS')
                with self.assertRaisesRegex(PermissionError, 'weekly_promotion_owner_confirmation_required'):
                    ladder.confirm_adoption(self.db, row['proposal_id'], 'system-weekly-ladder', 4, now,
                                            automatic=True)
                confirmation = ladder.confirm_adoption(self.db, row['proposal_id'], 'owner', 4, now)
                self.assertEqual(confirmation['status'], 'CONFIRMED')

    def test_one_proposal_per_platform_week_confirmation_is_atomic_cas_and_idempotent(self):
        rows=self.run_week()
        self.assertEqual(len(rows),3)
        self.assertEqual(self.db.get('pricing_plans','plan')['revision'],4)
        row=next(r for r in rows if r['platform']=='PS')
        with self.assertRaises(PermissionError):ladder.confirm_adoption(self.db,row['proposal_id'],'other-writer',4,NOW)
        confirmed=ladder.confirm_adoption(self.db,row['proposal_id'],'owner',4,NOW)
        self.assertEqual(confirmed['status'],'CONFIRMED')
        self.assertEqual(self.db.get('pricing_plans','plan')['revision'],5)
        self.assertEqual(self.db.get('pricing_plans','plan')['parameters']['market_anchor']['PS']['small']['p'],'0.09')
        self.assertEqual(ladder.confirm_adoption(self.db,row['proposal_id'],'owner',4,NOW),confirmed)
        other=next(r for r in rows if r['platform']=='PC')
        ladder.confirm_adoption(self.db,other['proposal_id'],'owner',5,NOW)
        self.assertEqual(self.db.get('pricing_plans','plan')['revision'],6)
        self.assertEqual(self.db.all('operations'),[])

    def test_expired_proposals_cannot_apply_and_automatic_requires_explicit_owner_enable_after_four_weeks(self):
        rows=self.run_week();row=rows[0]
        with self.assertRaisesRegex(ValueError,'four_manual_weeks'):
            ladder.set_automatic(self.db,'plan','owner',True,4,NOW)
        later=NOW+timedelta(days=28)
        self.assertFalse(self.db.get('metadata','weekly-ladder-control:plan')['automatic'])
        with self.assertRaises(ValueError):ladder.confirm_adoption(self.db,row['proposal_id'],'owner',4,later)
        self.assertEqual(self.db.get('ladder_proposals',row['proposal_id'])['status'],'EXPIRED')
        self.assertEqual(self.db.get('pricing_plans','plan')['revision'],4)
        with self.assertRaises(PermissionError):ladder.set_automatic(self.db,'plan','other-writer',True,4,later)
        self.assertTrue(ladder.set_automatic(self.db,'plan','owner',True,4,later)['automatic'])

    def test_notification_and_fs_order_keep_the_lowest_margin_platform_first(self):
        rows=self.run_week()
        for row in rows:
            row['margin_ratio']={'PS':'.15','XBOX':'.2','PC':'.4'}[row['platform']]
            self.db.put('ladder_proposals',row['proposal_id'],row)
        expected=['PS','XBOX','PC']
        self.assertEqual([r['platform'] for r in ladder.state(self.db)['proposals']],expected)
        self.assertEqual([r['platform'] for r in ladder.ordered_proposals(rows)],expected)

    def test_missing_week_does_not_start_the_four_week_manual_period(self):
        with patch('fc_pricing_v3.average_discount_v6.yesterday_es_ready',return_value=True), \
             patch.object(ladder,'read_week',side_effect=ValueError('weekly_days_incomplete')):
            with self.assertRaisesRegex(ValueError,'days_incomplete'):ladder.run(self.db,'plan',NOW)
        self.assertIsNone(self.db.get('metadata','weekly-ladder-control:plan'))
        self.assertEqual(self.db.all('ladder_proposals'),[])

    def test_rejection_and_stale_revision_do_not_change_parameters(self):
        rows=self.run_week();row=rows[0]
        with self.assertRaisesRegex(ValueError,'revision_changed'):
            ladder.confirm_adoption(self.db,row['proposal_id'],'owner',3,NOW)
        self.assertEqual(self.db.get('ladder_proposals',row['proposal_id'])['status'],'PROPOSED')
        self.assertEqual(ladder.reject(self.db,row['proposal_id'],'owner',NOW)['status'],'REJECTED')
        with self.assertRaises(ValueError):ladder.confirm_adoption(self.db,row['proposal_id'],'owner',4,NOW)
        self.assertEqual(self.db.get('pricing_plans','plan')['revision'],4)

    def test_api_uses_authenticated_actor_and_rejects_extra_parameter_fields(self):
        from fc_pricing_v3 import api
        row=self.run_week()[0]
        with patch.object(api,'ledger',return_value=self.db),patch.object(ladder,'confirm_adoption') as confirm:
            api.post('weekly-ladder/'+row['proposal_id']+'/confirm',{'expected_revision':4},'real-login')
            self.assertEqual(confirm.call_args.args[2],'real-login')
            with self.assertRaisesRegex(ValueError,'weekly_request_invalid'):
                api.post('weekly-ladder/'+row['proposal_id']+'/confirm',{'expected_revision':4,'p':'.15'},'real-login')

    def test_weekly_failure_does_not_requeue_finished_natural_price_job_or_run_for_manual(self):
        from fc_pricing_v3 import scheduler
        import json
        self.db.enqueue('cycle','natural',NOW,dict(plan_id='plan',revision=4))
        with self.db.connect() as conn:job=dict(conn.execute("SELECT * FROM durable_jobs WHERE id='natural'").fetchone())
        with patch.object(scheduler,'ledger',return_value=self.db),patch.object(scheduler,'clock',return_value=NOW), \
             patch.object(scheduler,'cycle',return_value={'status':'PROOF_INCOMPLETE'}), \
             patch.object(ladder,'run',side_effect=ValueError('weekly_days_incomplete')) as weekly:
            scheduler.run_job(job)
            weekly.assert_called_once()
            with self.db.connect() as conn:
                self.assertEqual(conn.execute("SELECT state FROM durable_jobs WHERE id='natural'").fetchone()[0],'done')
            self.assertTrue(any(r['code']=='weekly_ladder_incomplete' for r in self.db.all('incidents')))
            weekly.reset_mock()
            body=json.loads(job['body']);body['manual_requested']=True;job['body']=json.dumps(body)
            scheduler.run_job(job)
            weekly.assert_not_called()

    def test_week_source_uses_shared_facts_and_refuses_observed_or_partial_cost(self):
        import hashlib
        from fc_pricing_v3 import business_source, runtime
        start=NOW.date()-timedelta(days=7)
        key=hashlib.sha256(b'site266:FC27:Coins:order').hexdigest()
        shared=dict(rows=[dict(order_no='order',amount_usd_format='100',amount_rmb_format='700')],coverage=dict(
            publication_id='pin',source_revision='shared-v1',day_revisions={str(start+timedelta(days=i)):'v1' for i in range(7)}))
        attachment=dict(historical_orders_coverage={'window_complete':True},historical_orders=[dict(order_key=key,
            platform='PS',base_k='100',merchandise_before_discount_usd='110',paid_at=start.isoformat()+'T12:00:00+08:00')])
        actual=dict(order_no='order',status='\u5df2\u5b8c\u6210',actual_cost_cny='600',cost_coverage='complete',
                    cost_records=[{'cost_cny':'600','order_sale_cny':'800'}],admin_paid_usd='100')
        with patch.dict(sys.modules,{'shared_es_facts':SimpleNamespace(read=Mock(return_value=shared))}), \
             patch.object(business_source,'shared_curve_attachment',return_value=attachment), \
             patch.object(business_source,'_period_population',side_effect=AssertionError('retired_day_cache_read')), \
             patch.object(runtime,'ordinary_delivery_archives',return_value={'orders':[actual]}):
            week=ladder.read_week(start,NOW)
            self.assertEqual(week['platforms']['PS']['small'],dict(orders=1,merchandise_usd='110',revenue_cny='700',procurement_gross_cny='100'))
            for cost,coverage in (('600','partial'),(None,'complete')):
                actual.update(actual_cost_cny=cost,cost_coverage=coverage)
                with self.subTest(cost=cost,coverage=coverage), self.assertRaisesRegex(ValueError,'procurement_missing'):
                    ladder.read_week(start,NOW)

    def propose(self, previous=None, current=None, history=(), blocked=None):
        a,b=weeks()
        return ladder.propose_adoption(previous or a, current or b, market_anchor_parameters(),
                                       history=history, blocked=blocked or {}, now=NOW)

    def test_successful_raise_is_kept_and_failed_raise_rolls_back_and_freezes_two_weeks(self):
        action=dict(week_start='2026-11-16', platform='PS', band='small', delta_p='.01', status='CONFIRMED')
        a,b=weeks()
        b['platforms']['PS']['small']['orders']=95
        result=self.propose(a,b,[action])['proposals']
        self.assertEqual(next(r for r in result if r['platform']=='PS')['rule'], 'retain_raise')
        b['platforms']['PS']['small']['procurement_gross_cny']='1199'
        row=next(r for r in self.propose(a,b,[action])['proposals'] if r['platform']=='PS')
        self.assertEqual((row['rule'],row['delta_p'],row['freeze_until']), ('rollback_raise','-0.01','2026-12-07'))

    def test_market_adjusted_order_drop_lowers_small_two_points(self):
        a,b=weeks()
        for band in b['platforms']['PS'].values():band['orders']=80
        row=next(r for r in self.propose(a,b)['proposals'] if r['platform']=='PS')
        self.assertEqual((row['band'],row['delta_p'],row['rule']), ('small','-0.02','recover_orders'))

    def test_normal_week_raises_one_point_alternates_and_skips_a_capped_or_frozen_band(self):
        row=next(r for r in self.propose()['proposals'] if r['platform']=='PS')
        self.assertEqual((row['band'],row['delta_p']), ('small','0.01'))
        history=[dict(week_start='2026-11-09', platform='PS', band='small', delta_p='.01',status='CONFIRMED')]
        row=next(r for r in self.propose(history=history)['proposals'] if r['platform']=='PS')
        self.assertEqual(row['band'],'large')
        row=next(r for r in self.propose(blocked={'PS':{'small':['u7_cap']}})['proposals'] if r['platform']=='PS')
        self.assertEqual(row['band'],'large')
        history=[dict(week_start='2026-11-16',platform='PS',band='small',delta_p='-.01',status='CONFIRMED',freeze_until='2026-11-30')]
        row=next(r for r in self.propose(history=history)['proposals'] if r['platform']=='PS')
        self.assertEqual(row['band'],'large')

    def test_missing_day_or_unknown_money_does_not_make_a_proposal_and_market_is_bounded(self):
        a,b=weeks();b['days'].pop()
        self.assertEqual(self.propose(a,b)['proposals'],[])
        a,b=weeks();b['platforms']['PS']['small']['procurement_gross_cny']=None
        self.assertEqual(self.propose(a,b)['proposals'],[])
        a,b=weeks()
        for platform in ('XBOX','PC'):
            for band in b['platforms'][platform].values():band['orders']=200
        row=next(r for r in self.propose(a,b)['proposals'] if r['platform']=='PS')
        self.assertEqual(row['market_ratio'],'1.15')

    def test_partial_parameter_step_is_not_invented_at_the_bounds(self):
        a,b=weeks();parameters=market_anchor_parameters()
        for band in parameters['PS'].values():band['p']='.15'
        row=next(r for r in ladder.propose_adoption(a,b,parameters,now=NOW)['proposals'] if r['platform']=='PS')
        self.assertEqual(row['delta_p'],'0')


if __name__=='__main__':unittest.main()
