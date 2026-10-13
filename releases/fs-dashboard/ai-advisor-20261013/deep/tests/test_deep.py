import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from fc_deep_analysis import plan, build_evidence, attach_diagnostics, fallback, SHANGHAI
from advisor_memory import Memory
from fc_deep_model import project, validate
from fc_daily_model import MODEL
from fc_order_diagnostics import classify_logs, choose_sample, summarize

AT=datetime(2026,10,13,18,0,tzinfo=SHANGHAI)
CONFIG={'trust_customer_flag':False,'distribution_identification':'not_verified',
        'amount_edges_usd':[0,20,40,60,80,100,150,200,300,500],
        'attention_hours':24,'attention_amount_usd':300}


def fixture(start='2026-10-12',end='2026-10-12'):
    query=plan(start,end,AT)
    rows=[]
    cursor=datetime.fromisoformat(query['read_start']).replace(tzinfo=SHANGHAI)
    stop=datetime.fromisoformat(end).replace(tzinfo=SHANGHAI)
    while cursor<=stop:
        n=2 if cursor.date().isoformat()==start else 1
        for i in range(n):
            rows.append({'id':cursor.date().isoformat()+'-'+str(i),'site_group':'main','platform':'PS' if i==0 else 'PC','product':'Coins',
                         'amount_cents':10000,'customer':'unknown','customer_key':'PRIVATE_CUSTOMER_KEY',
                         'paid_at':cursor.isoformat(),'created_at':cursor.isoformat(),'updated_at':cursor.isoformat(),
                         'terminal':False,'backlog':True,'funding':False,'issue':i==1,'status':'问题单' if i==1 else '交易中',
                         'country':'US','device':'Desktop','payment':'Card','reason':'待确认'})
        cursor+=timedelta(days=1)
    data={'snapshot_id':'fc-detail-test','as_of':AT.isoformat(),'orders':rows,'backlog':rows[-4:],
          'data_status':'available','coverage':{'period':{'start':query['read_start']+' 00:00',
                                                       'end':(datetime.fromisoformat(end)+timedelta(days=1)).strftime('%Y-%m-%d %H:%M')},
                                             'paid_complete':True,'missing_days':[],'backlog_status':'available','site_rule':'fixture'}}
    return query,data,copy.deepcopy(CONFIG)


def evidence():
    return build_evidence(*fixture(),AT)


def model_response(e):
    findings=fallback(e)['findings'][:1]
    return {'model':MODEL,'id':'receipt-test','choices':[{'finish_reason':'stop','message':{'content':json.dumps({'findings':findings},ensure_ascii=False)}}],
            'usage':{'prompt_tokens':100,'completion_tokens':100,'total_tokens':200}}


class DateAndMath(unittest.TestCase):
    def test_daily_plan_one_capture(self):
        p=plan('2026-10-12','2026-10-12',AT)
        self.assertEqual(p['read_start'],'2026-09-12')
        self.assertEqual([w['key'] for w in p['windows']],['target','previous','week_ago','baseline7','baseline30'])
        self.assertEqual(p['limits']['captures'],1)

    def test_month_current_uses_complete_days(self):
        p=plan('2026-10-01','2026-10-13',AT)
        self.assertTrue(p['in_progress'])
        observed=next(w for w in p['windows'] if w['key']=='observed')
        previous=next(w for w in p['windows'] if w['key']=='previous')
        self.assertEqual(observed['end'],'2026-10-12')
        self.assertEqual(previous['days'],12)
        self.assertEqual(previous['start'],'2026-09-19')

    def test_today_only_no_fake_baseline(self):
        p=plan('2026-10-13','2026-10-13',AT)
        self.assertEqual(len(p['windows']),1)

    def test_shanghai_midnight(self):
        from datetime import timezone
        p=plan('2026-10-13','2026-10-13',datetime(2026,10,13,16,0,tzinfo=timezone.utc))
        self.assertFalse(p['in_progress'])

    def test_future_long_invalid(self):
        for start,end in [('2026-10-14','2026-10-14'),('2026-06-01','2026-10-12'),('2026-10-12','2026-10-11')]:
            with self.assertRaises(ValueError):plan(start,end,AT)

    def test_history_floor_missing_baseline(self):
        p=plan('2025-10-13','2025-10-13',AT)
        self.assertEqual(p['read_start'],'2025-10-13')
        self.assertFalse(next(w for w in p['windows'] if w['key']=='previous')['within_history'])

    def test_exact_amounts_and_additive_contribution(self):
        e=evidence();previous=e['comparisons'][0]['values']
        self.assertEqual(previous['revenue_usd']['delta'],100)
        self.assertEqual(previous['orders']['pct'],100)
        self.assertEqual(previous['average_order_usd']['delta'],0)
        for d in e['contributions']:
            self.assertEqual(sum(x['revenue_delta_usd'] for x in d['rows']),100)
        self.assertEqual([x['kind'] for x in e['investigations']],['sales_structure','order_problem_sample'])

    def test_day_mean_not_raw_sum(self):
        e=evidence();w=next(x for x in e['comparisons'] if x['baseline']=='baseline7')
        self.assertEqual(w['values']['orders']['baseline'],1)
        self.assertEqual(w['values']['revenue_usd']['baseline'],100)
        self.assertEqual(w['values']['average_order_usd']['baseline'],100)

    def test_missing_days_not_zero(self):
        q,d,c=fixture();d['coverage'].update(paid_complete=False,missing_days=['2026-10-11'])
        e=build_evidence(q,d,c,AT)
        self.assertEqual(next(w for w in e['windows'] if w['key']=='previous')['status'],'missing')
        self.assertNotIn('previous',[x['baseline'] for x in e['comparisons']])
        self.assertEqual(next(w for w in e['windows'] if w['key']=='target')['status'],'available')

    def test_unpriced_is_not_zero(self):
        q,d,c=fixture();d['orders'][-1]['amount_cents']=None
        e=build_evidence(q,d,c,AT)
        self.assertIsNone(e['windows'][0]['main']['revenue_usd'])
        self.assertIsNone(e['comparisons'][0]['values']['revenue_usd'])

    def test_zero_denominator(self):
        q,d,c=fixture();d['orders']=[r for r in d['orders'] if r['paid_at'].startswith('2026-10-12')]
        e=build_evidence(q,d,c,AT)
        v=e['comparisons'][0]['values']['revenue_usd']
        self.assertIsNone(v['pct']);self.assertTrue(v['zero_baseline'])

    def test_current_fulfillment_not_compared(self):
        e=evidence()
        self.assertNotIn('issues_share_pct',e['comparisons'][0]['values'])
        self.assertNotIn('unfinished_share_pct',e['comparisons'][0]['values'])

    def test_projection_contains_no_order_identity(self):
        p=project(evidence())
        serialized=json.dumps(p)
        self.assertNotIn('PRIVATE_CUSTOMER_KEY',serialized)
        self.assertNotIn('customer_key',serialized)
        self.assertNotIn('2026-10-12-1',serialized)

    def test_backlog_missing_not_zero(self):
        q,d,c=fixture();d['coverage']['backlog_status']='partial'
        e=build_evidence(q,d,c,AT)
        self.assertIsNone(e['backlog'])


class PrivateMemory(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.mem=Memory(self.tmp.name)
        self.body={'request_id':'memory_test_1','project':'FC27','kind':'strategy','text':'本周优先提升交付稳定性，促销调整先核查利润。',
                   'effective_start':'2026-10-01','effective_end':'2026-10-31'}

    def test_isolation_revocation_and_replay(self):
        r=self.mem.add_context('a',self.body,AT)
        self.assertEqual(self.mem.add_context('a',self.body,AT)['id'],r['id'])
        self.assertEqual(self.mem.contexts('b'),[])
        self.assertFalse(self.mem.revoke('b',r['id'],AT))
        self.assertTrue(self.mem.revoke('a',r['id'],AT));self.assertEqual(self.mem.contexts('a'),[])

    def test_context_time_and_unverified_label(self):
        self.mem.add_context('a',self.body,AT)
        self.assertFalse(self.mem.contexts('a')[0]['verified_by_source'])
        self.assertEqual(self.mem.contexts('a',period={'start':'2026-09-01','end':'2026-09-30'}),[])

    def test_sensitive_text_blocked(self):
        for text in ('密码: secret','联系客户a@example.com','Bearer abc','sk-AbcdEfgh'):
            with self.assertRaises(ValueError):self.mem.add_context('a',dict(self.body,text=text),AT)

    def test_memory_is_observation_not_ai_fact(self):
        e=evidence();out=fallback(e);out['findings'][0]['hypothesis']='SOME_AI_CAUSAL_CLAIM'
        self.mem.remember('a','report_12345',e,out,AT)
        next_e=copy.deepcopy(e);next_e['plan']['start']='2026-10-13'
        found=self.mem.recall('a',next_e)
        self.assertEqual(len(found['observations']),1)
        self.assertNotIn('SOME_AI_CAUSAL_CLAIM',json.dumps(found))
        self.assertFalse(found['observations'][0]['reviews'][0]['implementation_confirmed'])
        self.assertEqual(self.mem.recall('b',next_e)['observations'],[])

    def test_scope_change_blocks_memory_fact_comparison(self):
        e=evidence();self.mem.remember('a','report_12345',e,fallback(e),AT)
        e['scope_fingerprint']='changed';e['plan']['start']='2026-10-13'
        self.assertEqual(self.mem.recall('a',e)['observations'],[])

    def test_immutable_observation_and_forget(self):
        e=evidence();self.mem.remember('a','report_12345',e,fallback(e),AT)
        self.assertFalse(self.mem.remember('a','report_12345',e,fallback(e),AT))
        e['snapshot_id']='changed'
        with self.assertRaises(ValueError):self.mem.remember('a','report_12345',e,fallback(e),AT)
        self.assertEqual(self.mem.forget_observations('b'),0)
        self.assertEqual(self.mem.forget_observations('a'),1)


class OutputAndDiagnostics(unittest.TestCase):
    def test_valid_owner_report(self):
        e=evidence();p=project(e)
        self.assertEqual(validate(model_response(e),p)['tokens'],200)

    def test_hallucinated_ref_blocked(self):
        e=evidence();r=model_response(e);v=json.loads(r['choices'][0]['message']['content']);v['findings'][0]['refs']=['made-up']
        r['choices'][0]['message']['content']=json.dumps(v)
        with self.assertRaises(ValueError):validate(r,project(e))

    def test_numeric_invention_or_execution_claim_blocked(self):
        e=evidence()
        for text in ('预计增长百分之20','已退款所有问题订单'):
            r=model_response(e);v=json.loads(r['choices'][0]['message']['content']);v['findings'][0]['observation']=text
            r['choices'][0]['message']['content']=json.dumps(v)
            with self.assertRaises(ValueError):validate(r,project(e))

    def test_known_project_name_is_not_an_invented_number(self):
        e=evidence();r=model_response(e);v=json.loads(r['choices'][0]['message']['content'])
        v['findings'][0]['title']='FC27销售结构值得排查'
        r['choices'][0]['message']['content']=json.dumps(v)
        self.assertEqual(validate(r,project(e))['status'],'succeeded')
        v['findings'][0]['title']='FC270销售结构值得排查'
        r['choices'][0]['message']['content']=json.dumps(v)
        with self.assertRaises(ValueError):validate(r,project(e))

    def test_truncation_and_usage_fail_closed(self):
        e=evidence();r=model_response(e);r['choices'][0]['finish_reason']='length'
        with self.assertRaises(ValueError):validate(r,project(e))
        r=model_response(e);r['usage']['total_tokens']=201
        with self.assertRaises(ValueError):validate(r,project(e))

    def test_logs_private_text_never_survives(self):
        c=classify_logs([{'time':'26-10-13 17:55:17','status':'问题单','content':'密码错误，secret@example.com - password: PRIVATE_VALUE'}])
        self.assertEqual(c['category'],'credentials')
        self.assertNotIn('PRIVATE_VALUE',json.dumps(c));self.assertNotIn('@',json.dumps(c))

    def test_negation_resolution_ambiguous(self):
        for text in ('不是密码错误','密码错误已解决','市场未解锁并且密码错误','正常等待'):
            self.assertEqual(classify_logs([{'time':'26-10-13 17:55:17','status':'问题单','content':text}])['category'],'unclear')

    def test_sample_bounded_deduplicated_and_platform_balanced(self):
        rows=[{'id':str(i),'platform':['PS','PC','XBOX'][i%3],'amount_usd':i} for i in range(60)]
        samples=choose_sample(rows+rows)
        self.assertEqual(len(samples),12)
        self.assertEqual(set(r['platform'] for r in samples),{'PS','PC','XBOX'})
        self.assertEqual(len({r['id'] for r in samples}),12)

    def test_diagnostics_model_projection_drops_links_and_ids(self):
        e=evidence();d=summarize([{'id':'123'}],[{'ref':'order-123','platform':'PS','category':'credentials','review_url':'https://order.p2pah.cn/private'}],1,[],AT.isoformat())
        attach_diagnostics(e,d);p=project(e)
        self.assertNotIn('review_url',json.dumps(p));self.assertNotIn('order-123',json.dumps(p))


if __name__=='__main__':unittest.main()
