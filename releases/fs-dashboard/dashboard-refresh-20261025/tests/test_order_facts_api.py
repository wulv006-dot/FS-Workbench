"""D2 authenticated aggregate endpoint, without network or filesystem effects."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
import csv
import io
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'source'), str(ROOT.parent/'cache-archive-retention-20261025/source')]
from order_facts import build_order_facts
from order_facts_api import OrderFactsService, selection, public

DAY = (datetime.now(timezone(timedelta(hours=8))).date()-timedelta(days=2)).isoformat()


class Pool:
    def __init__(self):self.calls = []
    def submit(self, fn, *args):self.calls.append((fn, args))
    def run(self):
        fn, args = self.calls.pop(0)
        fn(*args)


def params(**extra):
    return {k: [v] for k, v in dict(mode='order-facts', start=DAY, end=DAY, **extra).items()}


def facts(scope):
    rows = [dict(site_id='266', order_no='PRIVATE-ORDER-'+str(i), amount_usd_format='50',
                 amount_rmb_format='350', status_format='已完成', pay_status='1',
                 paytime=DAY+' 10:00:00', gid='1327') for i in range(2)]
    attrs = [dict(site_id='266', order_no=rows[0]['order_no'], **{'归因渠道':'Direct'})]
    return build_order_facts(rows, attrs, [], sites={'266':'www.mmoexp.com'}, scope=scope,
            source_coverage=dict(admin_complete=True, source_revision='revision-1',
                                 raw={'order_no':'DO-NOT-EXPOSE'}))


class OrderFactsAPI(unittest.TestCase):
    def test_cost_revision_and_window_survive_with_same_admin_revision(self):
        query=selection(params());scope={k:v for k,v in query.items() if k!='channel'}
        outputs=[]
        for revision,observed in [('cost-r1','20'),('cost-r2','40')]:
            value=facts(scope)
            value['source_coverage']['cost']=dict(source_revision=revision,generated_at=DAY+'T10:00:00+08:00',
                period={'start':DAY,'end':DAY,'until':DAY+' 10:00','raw':'PRIVATE'},status='observed_only',
                shipment_window_complete=True,order_cost_complete=False,raw_order='PRIVATE')
            value['orders'][0]['observed_cost_cny']=observed
            outputs.append(public(value,query))
        self.assertEqual(outputs[0]['revisions']['source_revision'],outputs[1]['revisions']['source_revision'])
        self.assertEqual([v['revisions']['cost']['source_revision'] for v in outputs],['cost-r1','cost-r2'])
        self.assertEqual([v['totals']['observed_cost_cny'] for v in outputs],['20','40'])
        for value in outputs:
            self.assertFalse(value['revisions']['cost']['order_cost_complete'])
            self.assertEqual(value['revisions']['cost']['period']['until'],DAY+' 10:00')
            self.assertIsNone(value['totals']['procurement_gross_cny'])
            self.assertNotIn('PRIVATE',json.dumps(value))

    def test_first_response_exposes_existing_game_directory_even_for_empty_cohort(self):
        query=selection(params());scope={k:v for k,v in query.items() if k!='channel'}
        value=facts(scope);value['orders']=[]
        result=public(value,query,[('1327','FC27'),('456','Diablo 4')])
        self.assertEqual(result['options']['games'],[('1327','FC27'),('456','Diablo 4')])
        self.assertEqual(result['totals']['orders'],0)

    def setUp(self):
        self.now = 1000
        self.calls = []
        self.channels = SimpleNamespace(authorizer=lambda user: user in ('alice','bob'),
            pool=Pool(), lock=RLock(), jobs={}, actual_jobs={}, admission=nullcontext)
        def source(scope):
            self.calls.append(deepcopy(scope))
            return facts(scope)
        self.service = OrderFactsService(self.channels, source, clock=lambda:self.now)

    def complete(self, p=None, user='alice'):
        p = p or params()
        self.assertEqual(self.service.get(p,user)[0],202)
        self.channels.pool.run()
        return self.service.get(p,user)

    def test_auth_before_validation_or_source(self):
        self.assertEqual(self.service.get({'invalid':[]},'outsider')[0],403)
        self.assertEqual(self.service.get(params(),None)[0],403)
        self.assertFalse(self.channels.pool.calls)
        self.assertFalse(self.calls)

    def test_query_rejects_duplicates_unknown_dimensions_and_overwide_range(self):
        for p in (dict(params(),gid=['1','2']),dict(params(),refresh=['2']),params(site_id='0'),
                  params(channel='google'),dict(params(),start=['2000-01-01'])):
            with self.subTest(p=p), self.assertRaises(ValueError):selection(p)
        self.assertEqual(selection(params())['site_id'],'all')

    def test_pending_is_single_shared_job_then_aggregate_only(self):
        self.assertEqual(self.service.get(params(),'alice')[0],202)
        self.assertEqual(self.service.get(params(),'alice')[0],202)
        self.assertEqual(len(self.channels.pool.calls),1)
        self.assertEqual(list(self.channels.jobs.values()),['pending'])
        self.channels.pool.run()
        code,value=self.service.get(params(),'alice')
        self.assertEqual(code,200)
        self.assertEqual(value['totals']['orders'],2)
        self.assertEqual(value['totals']['admin_paid_usd'],'100')
        self.assertEqual(value['revisions'],{'source_revision':'revision-1','attribution':{},
            'cost':{'period':{},'order_cost_complete':False,'shipment_window_complete':False}})
        rendered=json.dumps(value)
        for forbidden in ('PRIVATE-ORDER','DO-NOT-EXPOSE','order_no','unlinked_admin_rows": ['):
            self.assertNotIn(forbidden,rendered)
        self.assertFalse(self.channels.jobs)
        value['totals']['orders']=99
        self.assertEqual(self.service.get(params(),'alice')[1]['totals']['orders'],2)

    def test_actor_scope_cache_and_channel_derived_selection(self):
        code,value=self.complete(params(channel='Direct'))
        self.assertEqual(code,200)
        self.assertEqual(value['totals']['orders'],1)
        self.assertEqual(value['coverage']['linked_orders'],2)
        self.assertEqual(value['channel_filter'],'derived_order_facts')
        self.assertNotIn('channel',self.calls[0])
        self.assertEqual(self.service.get(params(channel='Direct'),'bob')[0],202)
        self.assertEqual(self.service.get(params(channel='unknown'),'alice')[0],202)
        self.assertEqual(len(self.channels.pool.calls),2)

    def test_derived_scope_and_daily_rows_share_the_publication(self):
        next_day = (datetime.fromisoformat(DAY) + timedelta(days=1)).date().isoformat()
        q = selection(dict(params(gid='1327',site_id='266',channel='Direct'),end=[next_day]))
        scope = {k:v for k,v in q.items() if k!='channel'}
        value = facts(scope)
        value['orders'][1]['paid_at'] = next_day+' 00:00:00'
        result = public(value,q)
        self.assertEqual(result['effective_scope'],q)
        self.assertEqual(result['coverage_scope'],scope)
        self.assertEqual([(r['day'],r['orders'],r['admin_paid_usd'],r['status']) for r in result['trend']],
                         [(DAY,1,'50','available'),(next_day,0,None,'partial')])
        self.assertEqual(sum(r['orders'] for r in result['trend']),result['totals']['orders'])
        self.assertEqual(result['snapshot_id'],public(value,q)['snapshot_id'])
        rows = list(csv.reader(io.StringIO(result['aggregate_csv'].lstrip('\ufeff'))))
        self.assertEqual(rows[1][:5],[DAY,next_day,'266','1327','Direct'])
        self.assertEqual(rows[1][7],result['snapshot_id'])
        self.assertEqual([row[:9] for row in rows[3:]], [['来源明细','未提供','partial','1','50','0','','','0'],
                                   ['日期',DAY,'available','1','50','0','','','0'],
                                   ['日期',next_day,'partial','0','','0','','','0']])
        self.assertEqual(rows[3][9],'1.0')
        value['source_coverage']['attribution'] = {'publication_id':'new-revision'}
        self.assertNotEqual(result['snapshot_id'],public(value,q)['snapshot_id'])
        self.assertNotIn('PRIVATE-ORDER',json.dumps(result))

    def test_trend_keeps_complete_zero_and_does_not_fill_missing_amount(self):
        q = selection(params())
        scope = {k:v for k,v in q.items() if k!='channel'}
        value = facts(scope)
        value['orders'] = []
        self.assertEqual(public(value,q)['trend'][0]['admin_paid_usd'],'0')
        value = facts(scope)
        for row in value['orders']:row['admin_paid_usd'] = None
        result = public(value,q)
        self.assertEqual(result['trend'][0]['orders'],2)
        self.assertIsNone(result['trend'][0]['admin_paid_usd'])
        self.assertEqual(result['trend'][0]['missing_admin_usd_orders'],2)

    def test_unknown_payment_day_preserves_aggregate_without_inventing_daily_zero(self):
        q = selection(params())
        scope = {k:v for k,v in q.items() if k!='channel'}
        value = facts(scope)
        value['orders'][0]['paid_at'] = None
        value['orders'][1]['paid_at'] = DAY+' 10:72:00'
        result = public(value,q)
        self.assertEqual(result['totals']['orders'],2)
        self.assertEqual(result['totals']['admin_paid_usd'],'100')
        self.assertEqual(result['trend_unallocated_orders'],2)
        self.assertEqual(result['trend'][0]['orders'],0)
        self.assertIsNone(result['trend'][0]['admin_paid_usd'])
        self.assertEqual(result['trend'][0]['status'],'partial')

    def test_shared_two_slot_budget_counts_both_existing_services(self):
        self.channels.jobs['old']='pending'
        self.channels.actual_jobs['profit']='cost_pending'
        self.assertEqual(self.service.get(params(),'alice')[0],429)
        self.assertFalse(self.channels.pool.calls)
        self.channels.actual_jobs.clear()
        self.assertEqual(self.service.get(params(),'alice')[0],202)
        self.assertEqual(sum(v in ('pending','cost_pending') for v in self.channels.jobs.values()),2)
        self.assertEqual(self.service.get(params(),'bob')[0],429)

    def test_failures_sanitize_errors_and_do_not_loop_on_poll(self):
        def denied(scope):raise PermissionError('PRIVATE-ORDER-SECRET')
        self.service.source=denied
        code,value=self.complete()
        self.assertEqual(code,403)
        self.assertNotIn('SECRET',json.dumps(value))
        self.assertFalse(self.channels.pool.calls)
        self.assertFalse(self.channels.jobs)
        self.now+=61
        self.assertEqual(self.service.get(params(),'alice')[0],202)

    def test_source_scope_mismatch_fails_not_available(self):
        self.service.source=lambda scope:facts(dict(scope,site_id='other'))
        self.assertEqual(self.complete()[0],503)

    def test_effective_channel_source_share_and_coupon_evidence_are_one_cohort(self):
        query = selection(params(channel='PPC'))
        scope = {k:v for k,v in query.items() if k != 'channel'}
        value = facts(scope)
        value['orders'][0]['effective_attribution'] = dict(channel='PPC', basis='order_source',
            detail='google-FC27-PMAX-Coins-US', discount_code=True, promoter=None, coupon=True,
            coupon_templates=['Launch'], promotion_project=None, conflict=False)
        value['orders'][1]['effective_attribution'] = dict(channel='PPC', basis='native_channel',
            detail='https://youtube.com/watch?email=PRIVATE@example.com', discount_code=False,
            promoter=None, coupon=None, coupon_templates=[], promotion_project=None, conflict=False)
        result = public(value,query)
        self.assertEqual(result['totals']['orders'],2)
        self.assertEqual(result['breakdown']['denominator_orders'],2)
        self.assertEqual(result['breakdown']['dimension'],'source_detail')
        self.assertEqual({r['label']:r['order_share'] for r in result['breakdown']['rows']},
                         {'google-FC27-PMAX-Coins-US':0.5,'youtube.com':0.5})
        self.assertEqual(sum(r['associations']['coupon']['known_orders'] for r in result['breakdown']['rows']),1)
        self.assertEqual(sum(r['associations']['coupon']['unknown_orders'] for r in result['breakdown']['rows']),1)
        self.assertIn('google-FC27-PMAX-Coins-US',result['aggregate_csv'])
        self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertNotIn('/watch',result['aggregate_csv'])

    def test_native_referral_source_detail_survives_the_real_normalizer_and_projection(self):
        from channel_effects import Attribution
        from order_facts_runtime import effective_attribution
        query=selection(params(channel='Referral'))
        scope={k:query[k] for k in ('start','end','site_id','gid')}
        source=dict(site_id='266',order_no='fixture-order',amount_usd_format='20',amount_rmb_format='140',
                    status_format='已完成',pay_status='1',paytime=DAY+' 10:00:00',gid='1327')
        attribution={'site_id':'266','order_no':'fixture-order','归因渠道':'Referral','归因来源明细':'YouTube'}
        value=build_order_facts([source],[attribution],[],sites={'266':'www.mmoexp.com'},scope=scope,
                                source_coverage={'admin_complete':True})
        original=value['orders'][0]
        self.assertEqual(original['marketing_attribution']['source_raw'],'YouTube')
        self.assertEqual(public(value,query)['breakdown']['rows'][0]['label'],'YouTube')
        original['effective_attribution']=effective_attribution(original,source,None,Attribution({'entries':[]},[],{}))
        result=public(value,query)
        self.assertEqual(result['breakdown']['rows'][0]['label'],'YouTube')
        self.assertEqual(result['breakdown']['rows'][0]['order_share'],1)
        self.assertIn('YouTube',result['aggregate_csv'])

    def test_original_tracking_filters_apply_before_channel_and_to_export(self):
        query = selection(params(channel='PPC',status='valid',country='US',payment='PayPal',
            code='PRIVATE-CODE',coupon_template='7',coupon_batch='PRIVATE-BATCH',q='PRIVATE-ORDER'))
        scope = {k:query[k] for k in ('start','end','site_id','gid')}
        value = facts(scope)
        known = dict(orderNo='PRIVATE-ORDER-1',gid='1',refunded=False,country='US',payment='PayPal',
            codeKey='private-code',code='PRIVATE-CODE',promoter='Synthetic',
            coupons=[dict(templateId='7',batch='PRIVATE-BATCH',title='Launch')])
        value['orders'][0]['effective_attribution'] = dict(channel='PPC',detail='google-FC27-PMAX-Coins-US',filter_row=known)
        value['orders'][1]['effective_attribution'] = dict(channel='PPC',filter_row=dict(known,coupons=None))
        result=public(value,query)
        self.assertEqual(result['breakdown']['denominator_orders'],1)
        self.assertEqual(result['breakdown']['rows'][0]['order_share'],1)
        self.assertEqual(result['coverage']['unverified_filter_orders'],1)
        self.assertEqual(result['status'],'partial')
        self.assertTrue(result['keyword_applied'])
        self.assertNotIn('PRIVATE',json.dumps(result))
        self.assertNotIn('private-code',json.dumps(result))
        self.assertIn('discount_code_applied',result['aggregate_csv'])

    def test_detail_and_csv_use_original_actor_and_exact_cached_snapshot(self):
        query=params()
        _, result=self.complete(query)
        snap=result['snapshot_id']
        detail=params(snapshot_id=snap,detail_page='1')
        code,page=self.service.get(detail,'alice')
        self.assertEqual((code,page['total'],page['snapshot_id']),(200,2,snap))
        self.assertEqual(len(page['orders']),2)
        self.assertNotIn('orders',result)
        self.assertNotIn('PRIVATE-ORDER',json.dumps(result))
        self.assertIn('PRIVATE-ORDER',self.service.get(params(snapshot_id=snap,detail_export='1'),'alice')[1]['detail_csv'])
        self.assertEqual(self.service.get(detail,'outsider')[0],403)
        self.assertEqual(self.service.get(detail,'bob')[0],409)
        self.assertEqual(self.service.get(dict(detail,channel=['Direct']),'alice')[0],409)
        _, second=self.complete(query,user='bob')
        self.assertNotEqual(second['snapshot_id'],snap)
        self.assertEqual(self.service.get(detail,'bob')[0],409)
        self.now+=600
        self.assertEqual(self.service.get(detail,'alice')[0],409)
        self.assertFalse(self.channels.pool.calls)

    def test_shared_no_coverage_is_unavailable_and_has_no_daily_zero(self):
        query = selection(params())
        value=facts({k:query[k] for k in ('start','end','site_id','gid')})
        value.update(status='unavailable',orders=[])
        value['source_coverage'].update(admin_snapshot=True,admin_complete=False,missing_days=[DAY])
        result=public(value,query)
        self.assertEqual(result['status'],'unavailable')
        self.assertTrue(result['source_snapshot'])
        self.assertEqual(result['coverage']['missing_days'],[DAY])
        self.assertIsNone(result['trend'][0]['admin_paid_usd'])

    def test_slow_source_failure_returns_terminal_status_before_retry(self):
        def timed_out(scope):
            self.now += 180
            raise TimeoutError('PRIVATE-ORDER-SECRET')
        self.service.source = timed_out
        self.assertEqual(self.service.get(params(),'alice')[0],202)
        self.channels.pool.run()
        for force in ({}, {'refresh':'1'}):
            self.assertEqual(self.service.get(params(**force),'alice'),
                             (503, {'status':'source_failed','retryAfter':60}))
        self.assertFalse(self.channels.pool.calls)
        self.assertFalse(self.channels.jobs)
        self.now += 59
        self.assertEqual(self.service.get(params(),'alice')[1]['retryAfter'],1)
        self.now += 1
        self.assertEqual(self.service.get(params(),'alice')[0],202)
        self.assertEqual(len(self.channels.pool.calls),1)

    def test_refresh_reuses_key_waits_from_completion_then_captures_once(self):
        self.assertEqual(self.service.get(params(),'alice')[0],202)
        self.now+=80  # slow source: cooldown starts after completion, not submission
        self.channels.pool.run()
        code,value=self.service.get(params(refresh='1'),'alice')
        self.assertEqual(code,200)
        self.assertTrue(value['refresh_deferred'])
        self.assertEqual(value['retryAfter'],60)
        self.assertEqual(len(self.service.entries),1)
        self.assertFalse(self.channels.pool.calls)
        self.assertNotIn('refresh_deferred',self.service.get(params(),'alice')[1])
        self.now+=60
        self.assertEqual(self.service.get(params(refresh='1'),'alice')[0],202)
        self.assertEqual(self.service.get(params(refresh='1'),'alice')[0],202)
        self.assertEqual(self.service.get(params(),'alice')[0],202)
        self.assertEqual(len(self.channels.pool.calls),1)
        self.channels.pool.run()
        self.assertEqual(self.service.get(params(),'alice')[0],200)
        self.assertEqual(len(self.calls),2)
        self.assertEqual(len(self.service.entries),1)
        self.assertNotIn('refresh',self.calls[-1])

    def test_refresh_busy_keeps_cached_value_without_claiming_refresh(self):
        self.complete();self.now+=61
        self.channels.jobs.update(a='pending',b='pending')
        code,value=self.service.get(params(refresh='1'),'alice')
        self.assertEqual(code,200)
        self.assertEqual(value['totals']['orders'],2)
        self.assertEqual(value['refresh_reason'],'shared_workers_busy')
        self.assertTrue(value['refresh_deferred'])
        self.assertFalse(self.channels.pool.calls)

    def test_ttl_capacity_and_admission_failure_release_budget(self):
        self.complete()
        self.now+=601
        self.assertEqual(self.service.get(params(),'alice')[0],202)
        self.channels.pool.run()
        for i in range(1,34):self.complete(params(gid=str(i)))
        self.assertEqual(len(self.service.entries),32)
        def closed():raise BlockingIOError('no admission')
        self.channels.admission=closed
        self.assertEqual(self.service.get(params(gid='100'),'alice')[0],503)
        self.assertFalse(self.channels.jobs)


if __name__=='__main__':unittest.main()
