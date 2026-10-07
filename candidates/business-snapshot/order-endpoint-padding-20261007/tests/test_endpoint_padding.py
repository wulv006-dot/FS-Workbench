"""Offline synthetic schema and negative boundary tests. No browser or network."""
import copy
import json
import sys
import unittest
from pathlib import Path
from datetime import datetime, date, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'source'), str(ROOT/'dependencies')]
import profit_daily_reader as r
import profit_backfill as b
from profit_daily import normalise, merge

EXPECTED = {k: dict(sites='all-websites', gid=gid, tid='', status='')
            for k, gid in [('MMOEXP','0'), ('FC27','1322')]}

class Page:
    def __init__(self, raw): self.raw=raw; self.timeouts=[]
    def goto(self, *args, **kwargs): return type('Response', (), {'status':200})()
    def evaluate(self, *args): return copy.deepcopy(self.raw)
    def set_default_timeout(self, value): self.timeouts.append(value)

def fixture(name='all-sites'):
    return json.loads((ROOT/'tests/fixtures'/('synthetic-'+name+'.json')).read_text(encoding='utf-8'))

def parsed(f): return r.read_one(Page(f['raw']), f['item'], 20000)

class BoundaryTests(unittest.TestCase):
    def check_bad(self, mutate, code=None):
        f=fixture(); mutate(f)
        with self.assertRaises(ValueError) as raised: parsed(f)
        if code: self.assertEqual(str(raised.exception),code)
    def test_both_native_schemas_keep_negative_and_positive_margin(self):
        for name, rate in [('all-sites',-7.5),('fc27',18)]:
            f=fixture(name); out=parsed(f)
            self.assertEqual(len(out['rows']),24)
            self.assertEqual(out['seriesBoundaryAudit']['excludedZeroEndpointCount'],1)
            self.assertEqual(out['metrics']['profitMarginPct']['value'],rate)
            rows,audit=b.apply_results([f['item']],{f['item']['key']:out},EXPECTED)
            self.assertEqual((audit['available'],audit['zeroEndpointExclusions']),(1,1))
            self.assertEqual(normalise(rows[0],EXPECTED)['profitMarginPct'],rate)
    def test_without_tail_retains_all_inrange_points(self):
        f=fixture(); c=f['raw']['charts'][0];c['labels'].pop()
        for s in c['series']:s['data'].pop()
        out=parsed(f);self.assertEqual(len(out['rows']),24)
        self.assertEqual(out['seriesBoundaryAudit']['excludedZeroEndpointCount'],0)
    def test_short_hour_format_normalizes_same_boundary(self):
        f=fixture();f['raw']['charts'][0]['labels']=[x[:-3] for x in f['raw']['charts'][0]['labels']]
        self.assertEqual(len(parsed(f)['rows']),24)
    def test_nonzero_order_tail_rejected(self):
        self.check_bad(lambda f:f['raw']['charts'][0]['series'][0]['data'].__setitem__(-1,1),'primary_zero_sentinel_nonzero')
    def test_nonzero_amount_tail_rejected(self):
        self.check_bad(lambda f:f['raw']['charts'][0]['series'][1]['data'].__setitem__(-1,'0.001'),'primary_zero_sentinel_nonzero')
    def test_tiny_nonzero_amount_cannot_underflow_to_padding(self):
        self.check_bad(lambda f:f['raw']['charts'][0]['series'][1]['data'].__setitem__(-1,'1e-999'),'primary_zero_sentinel_nonzero')
    def test_negative_nonfinite_fractional_or_object_tail_rejected(self):
        for index,value in [(0,-1),(0,0.5),(1,'NaN'),(1,'Infinity'),(1,-0.1),(1,{'value':0}),(0,True)]:
            f=fixture();f['raw']['charts'][0]['series'][index]['data'][-1]=value
            with self.subTest(index=index,value=value),self.assertRaises(Exception):parsed(f)
    def test_nonmidnight_exclusive_tail_rejected(self):
        def change(f):
            f['item']['end']='2020-05-11 01:00';f['raw']['filters']['end_paytime']=f['item']['end']
            f['raw']['charts'][0]['labels'][-1]=f['item']['end']
        self.check_bad(change,'primary_zero_sentinel_scope_unverified')
    def test_partial_start_rejected(self):
        def change(f):
            f['item']['start']='2020-05-10 01:00';f['raw']['filters']['start_paytime']=f['item']['start']
            f['raw']['charts'][0]['labels'][0]='2020-05-10 01:00'
        self.check_bad(change)
    def test_multiday_padding_rejected(self):
        def change(f):
            f['item']['end']='2020-05-12 00:00';f['raw']['filters']['end_paytime']=f['item']['end']
            f['raw']['charts'][0]['labels'][-1]=f['item']['end']
        self.check_bad(change,'primary_zero_sentinel_scope_unverified')
    def test_multiday_without_padding_still_valid(self):
        f=fixture();f['item']['end']='2020-05-12 00:00';f['raw']['filters']['end_paytime']=f['item']['end']
        out=parsed(f);self.assertEqual(len(out['rows']),25)
        self.assertEqual(out['seriesBoundaryAudit']['excludedZeroEndpointCount'],0)
    def test_two_endpoint_tails_rejected(self):
        def change(f):
            c=f['raw']['charts'][0];c['labels'].append(c['labels'][-1])
            for s in c['series']:s['data'].append(0)
        self.check_bad(change,'primary_zero_sentinel_position_unverified')
    def test_tail_before_last_rejected(self):
        def change(f):
            c=f['raw']['charts'][0];c['labels'][-1],c['labels'][-2]=c['labels'][-2],c['labels'][-1]
        self.check_bad(change,'primary_zero_sentinel_position_unverified')
    def test_duplicate_hour_alias_rejected(self):
        self.check_bad(lambda f:f['raw']['charts'][0]['labels'].__setitem__(1,'2020-05-10 00'),'primary_duplicate_date_label')
    def test_real_outside_before_after_or_plain_date_rejected(self):
        for label in ['2020-05-09 23:00','2020-05-11 01:00','2020-05-11','2020-05-12 00:00']:
            with self.subTest(label=label):
                self.check_bad(lambda f:f['raw']['charts'][0]['labels'].__setitem__(-1,label))
    def test_invalid_calendar_or_hour_rejected(self):
        for label in ['2020-02-30 00:00','2020-05-10 24:00','2020-05-10 99','2020-05-10 00:01','unknown']:
            with self.subTest(label=label):
                self.check_bad(lambda f:f['raw']['charts'][0]['labels'].__setitem__(-1,label))
    def test_mixed_day_hour_rejected(self):
        self.check_bad(lambda f:f['raw']['charts'][0]['labels'].__setitem__(0,'2020-05-10'),'primary_mixed_date_granularity')
    def test_unknown_extra_metric_even_zero_rejected(self):
        for tail in [0,12]:
            with self.subTest(tail=tail):
                self.check_bad(lambda f:f['raw']['charts'][0]['series'].append({'name':'未知指标','data':[0]*24+[tail]}),'primary_series_schema_unverified')
    def test_duplicate_metric_names_rejected(self):
        self.check_bad(lambda f:f['raw']['charts'][0]['series'][1].__setitem__('name','订单数'),'primary_series_schema_unverified')
    def test_wrong_lengths_rejected(self):
        self.check_bad(lambda f:f['raw']['charts'][0]['series'][0]['data'].pop(),'primary_series_length_mismatch')
    def test_tail_only_never_fabricates_complete_day(self):
        def change(f):
            c=f['raw']['charts'][0];c['labels']=c['labels'][-1:]
            for s in c['series']:s['data']=[0]
        self.check_bad(change,'primary_series_dates_unavailable')
    def test_header_series_total_mismatch_rejected(self):
        self.check_bad(lambda f:f['raw']['charts'][0]['series'][0]['data'].__setitem__(0,4),'primary_series_totals_mismatch')
    def test_native_genuine_zero_day_preserved(self):
        f=fixture();f['raw']['metrics']=['0','$0.00','$0.00','$0.00','$0.00','0.00%']
        f['raw']['names']=[n+v for n,v in zip(['订单数量','订单金额','收款总额','货款总额','单均价','利润率'],f['raw']['metrics'])]
        for s in f['raw']['charts'][0]['series']:s['data']=[0]*25
        out=parsed(f);self.assertEqual((out['orders'],out['revenueUsd'],out['metrics']['profitMarginPct']['value']),(0,0,0))
    def test_original_label_parser_still_rejects_exclusive_end(self):
        with self.assertRaisesRegex(ValueError,'primary_hour_outside_period'):
            r.parse_daily_label('2020-05-11 00:00',datetime(2020,5,10),datetime(2020,5,11))

class SafeDiagnosticsTests(unittest.TestCase):
    def test_allowlists_identical(self):self.assertEqual(r.SAFE_FAILURE_CODES,b.SAFE_FAILURE_CODES)
    def test_unknown_exception_text_never_leaks(self):
        for exc in [ValueError('SYNTHETIC_PRIVATE_VALUE'),RuntimeError('SYNTHETIC_PRIVATE_VALUE')]:
            self.assertEqual(r.safe_failure_code(exc),'native_daily_read_failed')
        self.assertEqual(r.safe_failure_code(TimeoutError('SYNTHETIC_PRIVATE_VALUE')),'native_daily_read_timeout')
    def test_known_reason_persisted_in_collection_audit(self):
        f=fixture();code='primary_zero_sentinel_nonzero'
        rows,audit=b.apply_results([f['item']],{f['item']['key']:{'status':'unavailable','attemptedAt':'2020-05-12T00:00:00+00:00','errorCode':code}},EXPECTED)
        self.assertEqual(audit['failureReasonCounts'],{code:1});self.assertEqual(audit['failed'],1)
        self.assertIsNone(normalise(rows[0],EXPECTED)['profitMarginPct'])
    def test_unknown_result_reason_sanitized(self):
        f=fixture();rows,a=b.apply_results([f['item']],{f['item']['key']:{'status':'unavailable','attemptedAt':'2020-05-12T00:00:00+00:00','errorCode':'SYNTHETIC_PRIVATE_VALUE'}},EXPECTED)
        self.assertEqual(a['failureReasonCounts'],{'native_daily_read_failed':1})
        self.assertNotIn('SYNTHETIC_PRIVATE_VALUE',json.dumps([rows,a]))
    def test_invalid_timestamp_rejected_without_inventing_attempt(self):
        f=fixture()
        for when in [None,'bad','2020-05-12T00:00:00']:
            rows,a=b.apply_results([f['item']],{f['item']['key']:{'status':'unavailable','attemptedAt':when}},EXPECTED)
            self.assertEqual(rows,[]);self.assertEqual(a['attempted'],0)
            self.assertEqual(a['rejectionReasonCounts'],{'native_daily_timestamp_unverified':1})
    def test_bad_result_shape_isolated(self):
        f=fixture();rows,a=b.apply_results([f['item']],{f['item']['key']:[1]},EXPECTED)
        self.assertEqual(rows,[]);self.assertEqual(a['rejectionReasonCounts'],{'native_daily_result_shape_invalid':1})
    def test_old_good_point_kept_after_safe_failure(self):
        f=fixture();out=parsed(f);out['capturedAt']='2020-05-12T00:00:00+00:00'
        good,a=b.apply_results([f['item']],{f['item']['key']:out},EXPECTED)
        bad,a=b.apply_results([f['item']],{f['item']['key']:{'status':'unavailable','attemptedAt':'2020-05-12T02:00:00+00:00','errorCode':'primary_zero_sentinel_nonzero'}},EXPECTED)
        kept=merge(merge([],good,EXPECTED),bad,EXPECTED)[0]
        self.assertEqual(kept['profitMarginPct'],-7.5);self.assertTrue(kept['stale'])
    def test_boundary_audit_only_accepts_fixed_contract_count(self):
        f=fixture()
        for malformed in [{'schemaVersion':1,'contractId':r.SENTINEL_CONTRACT,'exclusiveEndPreserved':True,'excludedZeroEndpointCount':True},{'schemaVersion':1,'contractId':r.SENTINEL_CONTRACT,'exclusiveEndPreserved':True,'excludedZeroEndpointCount':2},{'schemaVersion':1,'contractId':'unknown','exclusiveEndPreserved':True,'excludedZeroEndpointCount':1}]:
            out=parsed(f);out['seriesBoundaryAudit']=malformed
            rows,a=b.apply_results([f['item']],{f['item']['key']:out},EXPECTED)
            self.assertEqual((a['available'],a['zeroEndpointExclusions']),(1,0))
    def test_auth_failure_still_aborts_remaining_without_raw_text(self):
        f=fixture();other=fixture('fc27');page=Page(f['raw'])
        def bad(*args):raise ValueError('primary_login_or_page_unavailable')
        out=r.collect_bounded(page,[f['item'],other['item']],30,clock=lambda:0,read=bad)
        self.assertEqual(out[f['item']['key']]['errorCode'],'primary_login_or_page_unavailable')
        self.assertEqual(out[other['item']['key']]['status'],'not_started_budget')
    def test_per_request_timeout_max20_and_budget_stops(self):
        f=fixture();g=fixture('fc27');clock=iter([0,28]);page=Page(f['raw'])
        out=r.collect_bounded(page,[f['item'],g['item']],30,clock=lambda:next(clock))
        self.assertEqual(page.timeouts,[20000]);self.assertEqual(out[g['item']['key']]['status'],'not_started_budget')
    def test_request_batch_limit_stays12_and_budget240(self):
        f=fixture();items=[dict(f['item'],key='synthetic-'+str(i)) for i in range(13)]
        with self.assertRaises(ValueError):r.validate_requests({'requests':items,'budgetSeconds':240})
        with self.assertRaises(ValueError):r.validate_requests({'requests':items[:12],'budgetSeconds':241})
        self.assertEqual(len(r.validate_requests({'requests':items[:12],'budgetSeconds':240})[0]),12)

if __name__=='__main__':unittest.main(verbosity=2)
