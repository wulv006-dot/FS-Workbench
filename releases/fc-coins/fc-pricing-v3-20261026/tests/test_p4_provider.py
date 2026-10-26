"""Isolated candidate tests: real current business helpers, no network or business writes."""
import hashlib
import json
import tempfile
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch, Mock

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'source'
sys.path.insert(0,str(SOURCE))
from fc_pricing_v3.financial import fingerprint
from fc_pricing_v3 import business_source as candidate
NOW=datetime(2026,10,26,13,tzinfo=timezone.utc)


def population(*paid_dates):
    return {'private-'+str(i):(dict(paidAt=day,salesUsd='10',status='已完成',coupons=[],deliveryRows=1,costCny='30',saleCny='60'),dict(discount_usd='0')) for i,day in enumerate(paid_dates)}


def provenance(period,status='complete'):
    return dict(period=period,status=status,canonical_archive_sha256=fingerprint(['canonical',period]),
        ES_source_sha256=fingerprint(['ES',period]),ES_complete=status=='complete',missing_product_identity=0,
        source_generated_at='2026-10-26T01:00:00+08:00')


def native_traces(session,pages,period,selected):
    return {key:dict(order_no=key,site_id=266,gid=1327,pay_status=1,
        amount_usd_format='10',amount_rmb_format='70',before_discount='10',discount=100,points=0,
        is_region_price=0,aid=21587,content='<span class="item">100 K coins+5K Free x 1 = $10</span>',
        timestamp=NOW.timestamp()-86400,timestamp_format=(NOW-timedelta(days=1)).astimezone(candidate.TZ).strftime('%Y-%m-%d %H:%M:%S')) for key in selected}, {}, {}


class HistoricalProviderTest(unittest.TestCase):
    def setUp(self):
        self.clock=patch.object(candidate,'_historical_provider_now',return_value=NOW)
        self.clock.start();self.addCleanup(self.clock.stop)

    def run_full(self,selector,selected,**kwargs):
        period=candidate.historical_period(selector,now=NOW)['period']
        with patch.object(candidate,'_period_population',return_value=(selected,provenance(period))) as read,patch.object(candidate,'_live_traces',side_effect=native_traces) as traces:
            result=candidate.collect_historical_attachment(selector,None,None,**kwargs)
        return result,read,traces

    def test_closed_selectors_default_seven_and_previous_complete_calendar_month(self):
        for selector,start,end in [('7d_closed','2026-10-19','2026-10-25'),('14d','2026-10-12','2026-10-25'),('28d_closed','2026-09-28','2026-10-25'),('previous_calendar_month','2026-09-01','2026-09-30')]:
            with self.subTest(selector=selector):
                window=candidate.historical_period(selector)
                self.assertEqual(window['period'],dict(start=start,end=end))
                self.assertTrue(window['paid_window_start'].endswith('+08:00'))
        self.assertEqual(candidate.historical_period(7)['period_selector'],'7d')
        for invalid in ('current_month',True,{'start':'2026-10-01','end':'2026-10-26'}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):candidate.historical_period(invalid)

    def test_fourteen_day_population_is_complete_even_when_counterfactual_fields_are_partial(self):
        result,read,traces=self.run_full('14d_closed',population('2026-10-12 00:00:00','2026-10-25 23:59:59'))
        coverage=result['historical_orders_coverage']
        self.assertEqual(coverage['period_selector'],'14d')
        self.assertTrue(coverage['window_complete'])
        self.assertEqual(coverage['population_status'],'complete')
        self.assertEqual(coverage['status'],'partial')
        self.assertEqual(len(result['historical_orders']),2)
        self.assertEqual(coverage['paid_window'],dict(start='2026-10-12',end_exclusive='2026-10-26',timezone='Asia/Shanghai'))
        self.assertEqual(result['paid_window'],coverage['paid_window'])
        self.assertEqual(result['period_selector'],coverage['period_selector'])
        self.assertEqual(result['source_sha256'],coverage['source_sha256'])
        self.assertEqual(coverage['totals']['net_paid_usd'],'20')
        self.assertEqual(read.call_count,1)
        self.assertEqual(traces.call_count,1)
        self.assertIn('historical_refund_revision_chain_not_collected',coverage['gaps'])

    def test_payment_window_is_inclusive_exclusive_in_Asia_Shanghai(self):
        result,_,_=self.run_full('14d',population('2026-10-11T16:00:00+00:00','2026-10-25T16:00:00+00:00','2026-10-11 23:59:59','unknown'))
        self.assertEqual(len(result['historical_orders']),1)
        coverage=result['historical_orders_coverage']
        self.assertEqual(coverage['population_selection']['excluded_outside_paid_window'],2)
        self.assertEqual(coverage['gaps']['canonical_paid_at_unknown'],1)
        self.assertFalse(coverage['window_complete'])

    def test_observed_at_cannot_backdate_newly_read_cost_or_order_facts(self):
        result,_,_=self.run_full('7d',population('2026-10-25 12:00:00'),observed_at=NOW-timedelta(days=30))
        self.assertEqual(result['historical_orders'][0]['available_at'],NOW.isoformat())
        self.assertEqual(result['historical_orders_coverage']['as_of'],NOW.isoformat())
        self.assertEqual(result['historical_orders'][0]['created_at'],'2026-10-25T13:00:00+00:00')

    def test_full_calendar_month_native_requests_reuse_at_most_28_day_windows(self):
        result,_,traces=self.run_full('last_complete_month',population('2026-09-01 10:00:00','2026-09-30 10:00:00'))
        self.assertEqual([call.args[2] for call in traces.call_args_list],[dict(start='2026-09-01',end='2026-09-28'),dict(start='2026-09-29',end='2026-09-30')])
        self.assertEqual(len(result['historical_orders']),2)

    def test_month_missing_canonical_days_keeps_existing_block_and_real_ES_coverage(self):
        target=candidate.historical_period('last_complete_month')['period']
        block=dict(start='2026-09-17',end='2026-09-30')
        selected=population('2026-09-20 10:00:00')
        missing=['2026-09-'+str(day).zfill(2) for day in range(1,17)]
        with patch.object(candidate,'_period_population',side_effect=[(None,dict(status='unavailable',reason='canonical_period_cache_missing')),(selected,provenance(block))]),patch.object(candidate,'_historical_existing_day_blocks',return_value=([block],missing)),patch.object(candidate,'_historical_existing_ES_coverage',return_value=dict(status='complete',source_sha256='e'*64,identified_Gold_orders=50)),patch.object(candidate,'_live_traces',side_effect=native_traces),patch.object(candidate,'_historical_native_population',side_effect=ValueError('admin_native_unavailable')):
            result=candidate.collect_historical_attachment('last_complete_month',None,None)
        coverage=result['historical_orders_coverage']
        self.assertEqual(coverage['period'],target)
        self.assertFalse(coverage['window_complete'])
        self.assertEqual(coverage['canonical_missing_days'],missing)
        self.assertEqual(coverage['existing_ES_coverage']['identified_Gold_orders'],50)
        self.assertEqual(coverage['totals']['net_paid_usd'],'10')
        self.assertEqual(len(result['historical_orders']),1)

    def test_missing_all_canonical_is_unknown_not_zero_even_with_existing_ES(self):
        with patch.object(candidate,'_period_population',return_value=(None,dict(status='unavailable'))),patch.object(candidate,'_historical_existing_day_blocks',return_value=([],['2026-09-01'])),patch.object(candidate,'_historical_existing_ES_coverage',return_value=dict(status='complete',source_sha256='e'*64,identified_Gold_orders=50)),patch.object(candidate,'_live_traces') as traces,patch.object(candidate,'_historical_native_population',side_effect=ValueError('admin_native_unavailable')):
            result=candidate.collect_historical_attachment('last_complete_month',None,None)
        coverage=result['historical_orders_coverage']
        self.assertEqual(coverage['population_status'],'unavailable')
        self.assertNotIn('net_paid_usd',coverage['totals'])
        self.assertFalse(coverage['window_complete'])
        traces.assert_not_called()

    def test_missing_month_days_are_filled_once_by_native_source_without_requerying_them(self):
        block=dict(start='2026-09-17',end='2026-09-30');missing=['2026-09-'+str(day).zfill(2) for day in range(1,17)]
        cached=population('2026-09-20 10:00:00')
        old=population('2026-09-10 10:00:00');backfilled={'native-order':old['private-0']}
        native,used,_=native_traces(None,None,dict(start=missing[0],end=missing[-1]),backfilled)
        proof=provenance(dict(start=missing[0],end=missing[-1]));proof['source_kind']='native_Admin_backfill'
        with patch.object(candidate,'_period_population',side_effect=[(None,dict(status='unavailable')),(cached,provenance(block))]),patch.object(candidate,'_historical_existing_day_blocks',return_value=([block],missing)),patch.object(candidate,'_historical_existing_ES_coverage',return_value=dict(status='complete',source_sha256='e'*64)),patch.object(candidate,'_historical_native_population',return_value=(backfilled,proof,native,used)) as backfill,patch.object(candidate,'_live_traces',side_effect=native_traces) as traces:
            result=candidate.collect_historical_attachment('last_complete_month',None,None)
        coverage=result['historical_orders_coverage']
        self.assertEqual(len(result['historical_orders']),2)
        self.assertEqual(coverage['totals']['net_paid_usd'],'20')
        self.assertEqual(coverage['canonical_missing_days'],missing)
        self.assertEqual(coverage['unresolved_population_days'],[])
        self.assertTrue(coverage['window_complete'])
        self.assertEqual(len(coverage['native_backfills']),1)
        backfill.assert_called_once_with(dict(start=missing[0],end=missing[-1]),None,None)
        self.assertTrue(all('native-order' not in call.args[3] for call in traces.call_args_list))
        self.assertNotIn('native-order',json.dumps(candidate.historical_attachment_summary(result)))

    def test_native_backfill_partial_ES_does_not_claim_complete_population(self):
        missing=['2026-09-01'];proof=provenance(dict(start=missing[0],end=missing[0]),status='partial')
        with patch.object(candidate,'_period_population',return_value=(None,dict(status='unavailable'))),patch.object(candidate,'_historical_existing_day_blocks',return_value=([],missing)),patch.object(candidate,'_historical_existing_ES_coverage',return_value=dict(status='complete',source_sha256='e'*64)),patch.object(candidate,'_historical_native_population',return_value=({},proof,{},{})):
            result=candidate.collect_historical_attachment('last_complete_month',None,None)
        coverage=result['historical_orders_coverage']
        self.assertEqual(coverage['population_status'],'partial')
        self.assertFalse(coverage['window_complete'])
        self.assertEqual(coverage['unresolved_population_days'],[])
        self.assertIn('canonical_or_ES_population_partial',coverage['gaps'])

    def test_native_helper_uses_original_accounting_ES_identity_and_bounded_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'channel_mapping.json').write_text('{}')
            raw=[dict(order_no=n,site_id=266,gid=1327,paytime='2026-09-10 12:00:00') for n in ('gold','item','refund','unknown','test')]
            normalized=[dict(orderNo=r['order_no'],gid='1327',status='已完成',salesUsd='2',payStatus='1',refunded=r['order_no']=='refund',testOrder=r['order_no']=='test') for r in raw]
            meta={hashlib.sha256(n.encode()).hexdigest():dict(product='Gold' if n!='item' else 'Items') for n in ('gold','item','refund','test')}
            channel=types.SimpleNamespace(__file__=str(root/'channel_source.py'),SALES=root,load_costs=Mock(return_value=([],{'status':'available'})),normalize=Mock(return_value=normalized),apply_cost_overrides=lambda _:dict(sources=dict(accounting={'status':'available'}),costOverrides={},testOrders={}))
            accounting=types.SimpleNamespace(accounting_row=Mock(side_effect=lambda row,*a,**k:row),fraud=lambda row:False)
            ES=types.SimpleNamespace(CoinsEvidence=lambda:types.SimpleNamespace(archive=root),GOLD='Gold',es_metadata=lambda *a:(meta,dict(complete=True,source_sha256='e'*64)))
            def read(session,path,*args):
                return raw if path.endswith('order.Order/index') else [dict(id='used',site_id=266,order_no='gold')] if path.endswith('MemberCouponLog/index') else []
            pages=Mock(side_effect=read);period=dict(start='2026-09-01',end='2026-09-16')
            with patch.dict(sys.modules,dict(channel_source=channel,channel_effects=accounting,coins_evidence=ES)):
                selected,proof,native,logs=candidate._historical_native_population(period,'session',pages)
            self.assertEqual(set(selected),{'gold'});self.assertEqual(set(native),{'gold'});self.assertEqual(set(logs),{'used'})
            self.assertEqual(proof['status'],'partial');self.assertEqual(proof['missing_product_identity'],1)
            self.assertEqual(proof['unclassified_paid_FC_usd'],'2');self.assertEqual(proof['native_rows'],5)
            self.assertEqual(pages.call_count,4);self.assertIn(('gid','=','1327'),pages.call_args_list[0].args[2])
            self.assertTrue(all(call.kwargs==dict(admin_revenue=True) for call in accounting.accounting_row.call_args_list))
            channel.load_costs.assert_called_once();channel.normalize.assert_called_once()

    def test_native_zero_orders_requires_an_actual_bounded_query_and_no_extra_reads(self):
        channel=types.SimpleNamespace(apply_cost_overrides=lambda _:dict(sources=dict(accounting={'status':'available'})))
        modules=dict(channel_source=channel,channel_effects=types.SimpleNamespace(accounting_row=None,fraud=None),coins_evidence=types.SimpleNamespace(CoinsEvidence=lambda:types.SimpleNamespace(archive='fixture'),es_metadata=lambda *a:({},dict(complete=True,source_sha256='e'*64)),GOLD='Gold'))
        pages=Mock(return_value=[])
        with patch.dict(sys.modules,modules):
            selected,proof,native,logs=candidate._historical_native_population(dict(start='2026-09-01',end='2026-09-01'),None,pages)
        self.assertEqual((selected,native,logs),({},{},{}));self.assertEqual(proof['status'],'complete')
        self.assertEqual(proof['native_rows'],0);self.assertEqual(pages.call_count,1)

    def test_native_helper_rejects_wrong_scope_before_reading_more_sources(self):
        modules=dict(channel_source=types.SimpleNamespace(),channel_effects=types.SimpleNamespace(accounting_row=None,fraud=None),coins_evidence=types.SimpleNamespace(CoinsEvidence=None,es_metadata=None,GOLD='Gold'))
        pages=Mock(return_value=[dict(site_id=999,gid=1327,paytime='2026-09-10 12:00:00')])
        with patch.dict(sys.modules,modules),self.assertRaisesRegex(ValueError,'historical_native_paid_scope_not_honored'):
            candidate._historical_native_population(dict(start='2026-09-01',end='2026-09-16'),None,pages)
        self.assertEqual(pages.call_count,1)

    def test_native_failure_is_not_retried_and_public_projection_contains_no_private_rows(self):
        period=candidate.historical_period('14d')['period']
        with patch.object(candidate,'_period_population',return_value=(population('2026-10-20 12:00:00'),provenance(period))),patch.object(candidate,'_live_traces',side_effect=ValueError('admin_page_failed')) as traces:
            result=candidate.collect_historical_attachment('14d',None,None)
        self.assertEqual(traces.call_count,1)
        public=candidate.historical_attachment_summary(result)
        self.assertNotIn('historical_orders',public)
        self.assertNotIn('private-0',json.dumps(public))
        self.assertEqual(public['gaps']['native_trace_read_failed'],1)
        self.assertNotIn('net_paid_usd',public['totals'])

    def test_same_failed_exact_source_is_not_read_twice(self):
        target=candidate.historical_period('14d')['period']
        with patch.object(candidate,'_period_population',side_effect=ValueError('invalid_day_cache')) as read,patch.object(candidate,'_historical_existing_day_blocks',return_value=([target],[])),patch.object(candidate,'_historical_existing_ES_coverage',return_value=dict(status='complete',source_sha256='e'*64)):
            result=candidate.collect_historical_attachment('14d',None,None)
        self.assertEqual(read.call_count,1)
        self.assertFalse(result['historical_orders_coverage']['window_complete'])

    def test_late_cost_revision_changes_private_fact_hash_without_overwriting_prior_result(self):
        selected=population('2026-10-20 12:00:00')
        first,_,_=self.run_full('14d',deepcopy(selected))
        selected['private-0'][0]['costCny']='35'
        second,_,_=self.run_full('14d',selected)
        self.assertEqual(first['historical_orders'][0]['order_key'],second['historical_orders'][0]['order_key'])
        self.assertNotEqual(first['historical_orders'][0]['source_sha256'],second['historical_orders'][0]['source_sha256'])
        self.assertEqual(first['historical_orders'][0]['cost_cny'],'30')
        self.assertEqual(second['historical_orders'][0]['cost_cny'],'35')


if __name__=='__main__':unittest.main()
