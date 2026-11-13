from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fc_pricing_v3 import business_source as source, daily, runtime
from fc_pricing_v3.ledger import Ledger
import test_business_source


class HourlyOutcomesTest(unittest.TestCase):
    def fixture(self):
        now,order,window=test_business_source.BusinessSourceTest().window_fixture()
        order.update(id='1',status_format='已完成',email='private@example.invalid')
        return now,order,window

    def test_incremental_payment_queries_keep_old_sample_and_backfill_original_cost(self):
        now,order,window=self.fixture()
        reads=[]
        def pages(session,path,filters,limit=100):
            if 'CouponLog' in path:return []
            span=next(f[2] for f in filters if f[0]=='paytime');reads.append(span)
            lower,upper=span.split(',')
            return [order] if lower<=order['paytime']<=upper else []
        accounting={order['order_no']:[dict(status='已完成',costCny=None,saleCny='60',salesUsd='8.68',
                         paidAt=order['paytime'],customerType='新客')]}
        with patch.object(source,'hourly_accounting',return_value={'archived':accounting,'cost_source':{}}),patch.dict('sys.modules',{'channel_source':MagicMock()}):
            first=source.incremental_window_context(None,pages,[window],now,{})
            self.assertEqual(len(first['online']['actual_outcomes']),1)
            self.assertIsNone(first['online']['actual_outcomes'][0]['actual_contribution_usd'])
            accounting[order['order_no']][0]['costCny']='42'
            later=source.incremental_window_context(None,pages,[window],now+timedelta(hours=1),first['state'])
        actual=later['online']['actual_outcomes']
        self.assertEqual(len(actual),1)
        self.assertEqual(actual[0]['actual_contribution_usd'],'2.604')
        self.assertEqual(actual[0]['price_window_id'],'op')
        self.assertEqual(actual[0]['order_key'],first['online']['actual_outcomes'][0]['order_key'])
        self.assertTrue(any((now-timedelta(minutes=1)).astimezone(source.TZ).strftime('%Y-%m-%d %H:%M:%S') in span for span in reads[1:]))
        self.assertNotIn('private@example.invalid',json.dumps(later))
        self.assertNotIn(order['order_no'],json.dumps(later['online']))

    def test_completed_orders_are_rechecked_and_refund_replaces_prior_outcome(self):
        now,order,window=self.fixture()
        def pages(session,path,filters,limit=100):
            if 'CouponLog' in path:return []
            lower,upper=next(f[2] for f in filters if f[0]=='paytime').split(',')
            return [order] if lower<=order['paytime']<=upper else []
        with patch.object(source,'hourly_accounting',return_value={'archived':{},'cost_source':{}}),patch.dict('sys.modules',{'channel_source':MagicMock()}):
            first=source.incremental_window_context(None,pages,[window],now,{})
            order.update(status='111',status_format='已退款')
            later=source.incremental_window_context(None,pages,[window],now+timedelta(hours=1),first['state'])
        self.assertEqual(later['online']['actual_outcomes'],[])
        self.assertEqual(later['online']['learning_coverage']['gap_events'][0]['reason'],'refund_or_unpaid')

    def test_source_failure_does_not_advance_mutable_input_state(self):
        now,order,window=self.fixture()
        prior={'cursor_at':(now-timedelta(hours=1)).isoformat(),'rows':{'1':order},'coupon_logs':{},'rechecked_days':{}}
        snapshot=deepcopy(prior)
        with self.assertRaisesRegex(ValueError,'page_failed'):
            source.incremental_window_context(None,MagicMock(side_effect=ValueError('page_failed')),[window],now,prior)
        self.assertEqual(prior,snapshot)

    def test_saved_orders_get_same_order_pinned_es_flags_without_recollecting_membership(self):
        now, order, window = self.fixture()
        closed = order['paytime'][:10]
        second = dict(order, id='2', order_no='second', email='another@example.invalid')
        third = dict(order, id='3', order_no='third', email='third@example.invalid')
        fourth = dict(order, id='4', order_no='fourth', email='fourth@example.invalid')
        orders = [order, second, third, fourth]
        def pages(session, path, filters, limit=100):
            if 'CouponLog' in path:
                return []
            lower, upper = next(f[2] for f in filters if f[0]=='paytime').split(',')
            return [row for row in orders if lower <= row['paytime'] <= upper]
        archived = {r['order_no']: [dict(status='已完成', costCny='42', saleCny='60', salesUsd='8.68',
                    paidAt=order['paytime'], customerType='老客')] for r in orders}
        archived[order['order_no']][0]['customerType'] = '新老客未提供'
        with patch.object(source, 'hourly_accounting', return_value={'archived': archived, 'cost_source': {}}):
            prior = source.incremental_window_context(None, pages, [window], now, {})

        es = MagicMock()
        es.latest_publication.return_value = dict(publication_id='se_test', cutoff=(now.astimezone(source.TZ).date() + timedelta(days=1)).isoformat())
        es.read.return_value = dict(status='available', coverage=dict(publication_id='se_test', data_revision='7', day_revisions={closed:'d1'}),
                                    rows=[], dataset={}, identity_catalog={})
        projector = MagicMock()
        projector.project_order_facts.return_value = dict(orders=[
            dict(site_id='266', gid='1327', paid_at=order['paytime'], order_no=order['order_no'], pinned_customer_flag='是'),
            dict(site_id='266', gid='1327', paid_at=order['paytime'], order_no='second', pinned_customer_flag_conflict=True),
            dict(site_id='320', gid='1327', paid_at=order['paytime'], order_no='third', pinned_customer_flag='是'),
        ])
        with patch.dict('sys.modules', {'shared_es_facts': es, 'order_facts_source': projector}), \
                patch.object(source, 'hourly_accounting', return_value={'archived': archived, 'cost_source': {}}):
            later = source.incremental_window_context(None, pages, [window], now, prior['state'], use_shared_customer_flags=True)
        def order_key(row):
            return hashlib.sha256(('FC27:266:' + row['order_no']).encode()).hexdigest()
        old = {r['order_key']: r for r in prior['online']['actual_outcomes']}
        updated = {r['order_key']: r for r in later['online']['actual_outcomes']}
        self.assertEqual([updated[order_key(r)]['new_customer'] for r in orders], [True, None, False, False])
        self.assertEqual({k: {n: v for n, v in r.items() if n != 'new_customer'} for k, r in old.items()},
                         {k: {n: v for n, v in r.items() if n != 'new_customer'} for k, r in updated.items()})
        proof = later['online']['learning_coverage']['customer_coverage']['shared_es']
        self.assertEqual(proof['publication_id'], 'se_test')
        self.assertEqual(proof['day_revisions'], {closed:'d1'})
        self.assertEqual(proof['flag_conflicts'], 1)
        es.read.assert_called_once_with(dict(start=closed, end=closed, site_id='266', gid='1327'), publication_id='se_test')
        self.assertNotIn('another@example.invalid', json.dumps(later))

    def test_hourly_failure_preserves_last_success_context_and_private_cursor(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'test.db')
            p=dict(plan_id='p',revision=1,mode='smart',state='ACTIVE',smart_strategy_version='smart-bidirectional-v2',
                   starts_at='2026-10-26T00:00:00+00:00',smart_started_at='2026-10-26T00:00:00+00:00')
            db.put('pricing_plans','p',p)
            db.put('metadata','daily_online_context',{'actual_outcomes':[{'order_key':'old'}]})
            _,_,window=self.fixture();db.put('actual_price_windows','op',window)
            with patch.object(runtime,'ledger',return_value=db),patch.object(daily.subprocess,'run',return_value=MagicMock(returncode=1)):
                with self.assertRaisesRegex(ValueError,'hourly_outcome_collection_failed'):
                    daily.run_hourly({'plan_id':'p','revision':1})
            self.assertEqual(db.get('metadata','daily_online_context'),{'actual_outcomes':[{'order_key':'old'}]})

    def test_success_persists_full_context_and_source_together_without_model(self):
        from fc_pricing_v3.smart import policy_suffix
        now,_,window=self.fixture()
        p=dict(plan_id='p',revision=1,mode='smart',state='ACTIVE',smart_strategy_version='smart-bidirectional-v2',
               starts_at=window['opened_at'],smart_started_at=window['opened_at'])
        online={'actual_outcomes':[{'order_key':'old'},{'order_key':'new'}],
                'learning_coverage':{'query_complete':True,'observed_at':now.isoformat(),'gap_events':[]}}
        result={'state':{'cursor_at':now.isoformat()},'online':online}
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'test.db');db.put('pricing_plans','p',p);db.put('actual_price_windows','op',window)
            def slow_collection(command,**kwargs):
                self.assertFalse(json.loads(kwargs['input'])['use_shared_customer_flags'])
                if kwargs['timeout']<300:
                    raise __import__('subprocess').TimeoutExpired(command,kwargs['timeout'])
                return MagicMock(returncode=0,stdout=json.dumps(result))
            with patch.object(runtime,'ledger',return_value=db),patch.object(daily.subprocess,'run',side_effect=slow_collection):
                receipt=daily.run_hourly({'plan_id':'p','revision':1})
            self.assertEqual(receipt['outcomes'],2)
            self.assertFalse(receipt['model_called'])
            self.assertFalse(receipt['price_write_performed'])
            self.assertEqual(db.get('metadata','smart-outcome-source:'+policy_suffix(p)),result['state'])
            self.assertEqual(db.get('metadata','daily_online_context')['actual_outcomes'],online['actual_outcomes'])

    def test_curve_daily_and_sprint_share_original_hourly_runner_and_keep_legacy_context(self):
        from fc_pricing_v3.dispatch import CURVE_WRITE_PROTOCOL
        from fc_pricing_v3.smart import policy_suffix

        now, _, window = self.fixture()
        online = {'actual_outcomes': [{'order_key': 'curve-order'}],
                  'learning_coverage': {'query_complete': True, 'observed_at': now.isoformat(), 'gap_events': []}}
        outcome = {'state': {'cursor_at': now.isoformat()}, 'online': online}
        for mode in ('daily', 'revenue_sprint'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                db = Ledger(Path(folder)/'test.db')
                plan = dict(plan_id='p', revision=1, mode=mode, state='ACTIVE', starts_at=window['opened_at'],
                            write_protocol=CURVE_WRITE_PROTOCOL)
                db.put('pricing_plans', 'p', plan)
                db.put('actual_price_windows', 'op', dict(window, origin='observed_native_curve_window'))
                legacy = {'actual_outcomes': [{'order_key': 'legacy-order'}]}
                db.put('metadata', 'daily_online_context', legacy)
                with patch.object(runtime, 'ledger', return_value=db), \
                        patch.object(daily.subprocess, 'run', return_value=MagicMock(returncode=0, stdout=json.dumps(outcome))) as read:
                    receipt = daily.run_hourly({'plan_id': 'p', 'revision': 1})
                self.assertEqual(receipt['status'], 'updated')
                request = json.loads(read.call_args.kwargs['input'])
                self.assertEqual(request['action'], 'hourly_outcomes')
                self.assertTrue(request['use_shared_customer_flags'])
                self.assertEqual(db.get('metadata', 'curve-outcome-source:'+policy_suffix(plan)), outcome['state'])
                self.assertEqual(db.get('metadata', 'curve-online-context:p')['actual_outcomes'], online['actual_outcomes'])
                self.assertEqual(db.get('metadata', 'daily_online_context'), legacy)

    def test_daily_profit_uses_independent_platform_label(self):
        import test_daily_profit
        fixture=test_daily_profit.DailyProfit();fixture.setUp()
        fixture.ops[0]['bundle']['smart_assignment']={'label':'MIXED','group_labels':{'PS':'B','XBOX':'A','PC':'C'}}
        console=daily.profit_summary(fixture.online,fixture.windows,fixture.ops,'2026-11-06','p')
        pc=daily.profit_summary(fixture.online,fixture.windows,fixture.ops,'2026-11-07','p')
        self.assertEqual(console['review_day']['groups'][0]['label'],'B')
        self.assertEqual(pc['review_day']['groups'][0]['label'],'C')

    def test_cost_feed_failure_keeps_cost_cursor_for_retry(self):
        now,order,window=self.fixture()
        prior={'cursor_at':(now-timedelta(hours=1)).isoformat(),'cost_cursor_at':window['opened_at'],
               'rows':{},'coupon_logs':{},'rechecked_days':{}}
        with patch.object(source,'hourly_accounting',return_value={'archived':{},'cost_source':{'status':'unavailable'}}) as accounting:
            result=source.incremental_window_context(None,MagicMock(return_value=[]),[window],now,prior)
        self.assertEqual(result['state']['cost_cursor_at'],prior['cost_cursor_at'])
        self.assertEqual(result['state']['cursor_at'],now.isoformat())
        self.assertEqual(result['online']['learning_coverage']['cost_source']['status'],'unavailable')

    def test_historical_zero_order_days_still_receive_unbiased_rechecks(self):
        now,_,window=self.fixture()
        later=now+timedelta(days=2)
        prior={'cursor_at':(later-timedelta(hours=1)).isoformat(),'rows':{},'coupon_logs':{},'rechecked_days':{}}
        pages=MagicMock(return_value=[])
        with patch.object(source,'hourly_accounting',return_value={'archived':{},'cost_source':{}}):
            result=source.incremental_window_context(None,pages,[window],later,prior)
        self.assertIn('2026-10-26',result['online']['learning_coverage']['historical_recheck_days'])

    def test_three_day_late_historical_trade_cost_is_read_again(self):
        now,order,window=self.fixture()
        late=now+timedelta(days=3)
        order.pop('email');order['customer_key']=hashlib.sha256(b'private@example.invalid').hexdigest()
        prior={'cursor_at':(late-timedelta(hours=1)).isoformat(),'cost_cursor_at':(late-timedelta(hours=1)).isoformat(),
               'rows':{'1':order},'coupon_logs':{},'rechecked_days':{'2026-10-26':late.isoformat()},
               'pending_cost_days':['2026-10-26']}
        def accounting(rows,logs,start,at,cost_since):
            cost='42' if cost_since<=now else None
            return {'archived':{order['order_no']:[dict(status='已完成',costCny=cost,saleCny='60',salesUsd='8.68',
                     paidAt=order['paytime'],customerType='新客')]},'cost_source':{}}
        with patch.object(source,'hourly_accounting',side_effect=accounting):
            result=source.incremental_window_context(None,MagicMock(return_value=[]),[window],late,prior)
        self.assertEqual(result['online']['actual_outcomes'][0]['actual_contribution_usd'],'2.604')
        self.assertEqual(result['state']['pending_cost_days'],[])


if __name__=='__main__':unittest.main()
