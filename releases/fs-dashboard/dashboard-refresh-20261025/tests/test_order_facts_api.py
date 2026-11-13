"""D2 authenticated aggregate endpoint, without network or filesystem effects."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
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
