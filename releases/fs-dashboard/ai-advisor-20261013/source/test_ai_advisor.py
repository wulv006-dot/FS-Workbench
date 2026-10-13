import ast
import copy
from datetime import datetime,timezone,timedelta
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
import re
import ai_advisor as a
import ai_advisor_model as m
from fc_daily import DailyReports

AT=datetime(2026,10,13,16,0,tzinfo=timezone(timedelta(hours=8)))
CAT={'catalogId':'catalog-abcd','profiles':{k:{'key':k,'name':k} for k in ('MMOEXP','FC27','NBA2K27','D4','RS')},
     'dashboard':{'groups':[{'key':'sports','profiles':['FC27','NBA2K27']},{'key':'rpg','profiles':['D4']},{'key':'general','profiles':['RS']}]}}
HEADERS={'X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin'}
def raw(key='FC27',start='2026-10-12',end='2026-10-12',orders=10):
    stop=(datetime.fromisoformat(end)+timedelta(days=1)).strftime('%Y-%m-%d 00:00')
    period={'start':start+' 00:00','end':stop}
    metric=lambda v:{'status':'available','value':v}
    admin={'status':'available','currency':'USD','period':period,'capturedAt':AT.isoformat(),
           'metrics':{'orders':metric(orders),'revenueUsd':metric(200),'newCustomers':metric(3),'repeatRatePct':metric(40)},
           'dimensions':{'channels':[{'code':'www.mmoexp.com','orders':orders,'revenueUsd':200}]}}
    order={'status':'available','currency':'USD','period':period,'capturedAt':AT.isoformat(),
           'metrics':{'profitMarginPct':metric(20),'fulfillmentRatePct':metric(90)}}
    return {'scopeContractId':'admin-main-order-labelled-supplement-v1','currency':'USD','query':{'start':start,'end':end},
            'profile':{'key':key,'period':period,'supplement':admin,'primary':order},'stale':False,'generatedAt':AT.isoformat(),'rangeId':'range-'+key}
def spec(**kw):return dict({'scope':'project','project':'FC27','kind':'day','anchor':'2026-10-12'},**kw)

class Dates(unittest.TestCase):
    def test_quarters_and_leap(self):
        q=a.period({'kind':'quarter','anchor':'2026-07-19'},AT)
        self.assertEqual((q['start'],q['end'],q['end_exclusive']),('2026-07-01','2026-09-30','2026-10-01'))
        p=a.period({'kind':'month','anchor':'2024-02-20'},AT.replace(year=2024,month=3))
        self.assertEqual(p['end'],'2024-02-29')
    def test_current_period_and_yesterday(self):
        self.assertTrue(a.period({'kind':'quarter','anchor':'2026-10-01'},AT)['in_progress'])
        q=a.period({'kind':'last7'},AT);self.assertEqual((q['start'],q['end']),('2026-10-06','2026-10-12'))
        self.assertEqual(a.period({'kind':'week','anchor':'2026-10-12'},AT)['end'],'2026-10-13')
    def test_limits_and_scope(self):
        for s in (spec(anchor='2026-10-14'),spec(kind='custom',start='2025-01-01',end='2026-10-12'),spec(project='NEW'),spec(scope='guessed')):
            with self.assertRaises(ValueError):a.selection(s,CAT,AT)
        self.assertEqual(a.selection(spec(scope='global'),CAT,AT)['projects'],['MMOEXP'])
        self.assertEqual(a.selection(spec(scope='rpg'),CAT,AT)['projects'],['D4'])

class Facts(unittest.TestCase):
    def setUp(self):self.p=a.period(spec(),AT)
    def test_native_unique_and_rate_not_summed(self):
        sel=a.selection(spec(scope='sports'),CAT,AT)
        rows=[a.project_facts(k,k,raw(k),self.p) for k in sel['projects']]
        report=a.report_from(sel,rows,AT)
        self.assertEqual(report['totals'],{'orders':20,'revenueUsd':400})
        self.assertNotIn('newCustomers',report['totals'])
        self.assertNotIn('repeatRatePct',report['totals'])
        self.assertEqual(report['projects'][0]['metrics']['newCustomers']['value'],3)
    def test_missing_main_never_uses_all_sites(self):
        item=raw();item['profile']['supplement']['dimensions']['channels'][0]['code']='another-site'
        r=a.project_facts('FC27','FC27',item,self.p)
        self.assertIsNone(r['metrics']['revenueUsd']['value']);self.assertEqual(r['status'],'partial')
    def test_zero_is_not_missing(self):
        item=raw();ad=item['profile']['supplement'];ad['dimensions']['channels']=[]
        for k in ('orders','revenueUsd'):ad['metrics'][k]['value']=0
        self.assertEqual(a.project_facts('FC27','FC27',item,self.p)['metrics']['orders']['value'],0)
    def test_mismatched_period_currency_and_stale_order(self):
        for field,value in [('scopeContractId','bad'),('currency','CNY')]:
            r=raw();r[field]=value
            with self.assertRaises(ValueError):a.project_facts('FC27','FC27',r,self.p)
        r=raw();r['profile']['period']['end']='2026-10-12 23:59'
        with self.assertRaises(ValueError):a.project_facts('FC27','FC27',r,self.p)
        r=raw();r['profile']['primary']['stale']=True
        self.assertIsNone(a.project_facts('FC27','FC27',r,self.p)['metrics']['profitMarginPct']['value'])
    def test_in_progress_not_cross_project_sum(self):
        s=a.selection(spec(kind='month',anchor='2026-10-01'),CAT,AT)
        r=a.project_facts('FC27','FC27',raw(start='2026-10-01',end='2026-10-13'),s['period'])
        self.assertIsNone(a.report_from(s,[r],AT)['totals']['orders'])
    def test_projection_no_pii_or_unapproved_profit(self):
        s=a.selection(spec(),CAT,AT);r=a.report_from(s,[a.project_facts('FC27','FC27',raw(),s['period'])],AT)
        r['secret']='raw customer';r['projects'][0]['raw_note']='someone@example.com'
        p=m.projection(r,'哪些指标需要核对？')
        self.assertNotIn('raw customer',json.dumps(p));self.assertNotIn('example.com',json.dumps(p));self.assertNotIn('profit',json.dumps(p))
        for q in ('密码: abcd','a@example.com','https://private.example.org/x','sk-abcd1234'):
            with self.assertRaises(ValueError):m.clean_question(q)

class Workspace(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.calls=[]
        self.daily=DailyReports(None,Path(self.temp.name)/'daily',clock=lambda:AT,is_configured=lambda:True)
        self.work=a.Advisor(lambda:copy.deepcopy(CAT),self.read,self.daily,Path(self.temp.name)/'advisor',clock=lambda:AT,authorizer=lambda u:u in ('alice','bob'),model=self.model)
    def tearDown(self):self.temp.cleanup()
    def read(self,p):return 200,raw(p['profile'][0],p['start'][0],p['end'][0])
    def model(self,p):self.calls.append(p);return {'status':'succeeded','analysis':'按现有来源核对数据。','suggestion':'核对缺项再作经营判断。','references':['FC27.orders'],'tokens':10,'response_id':'receipt-test'}
    def submit(self,user='alice',rid='request_12345',**kwargs):return self.work.post(dict(kind='report',request_id=rid,selection=spec(),ai=True,**kwargs),user,HEADERS)
    def test_dedup_conflict_and_private_read(self):
        code,job=self.submit();self.assertEqual(code,202)
        self.assertEqual(self.submit()[1]['job_id'],job['job_id'])
        self.assertEqual(self.work.post({'kind':'report','request_id':'request_12345','selection':spec(scope='sports')},'alice',HEADERS)[0],409)
        self.assertEqual(self.work.get({'id':[job['job_id']]},'bob')[0],404)
        self.assertEqual(self.work.get({},'bob')[1]['history'],[])
    def test_auth_and_csrf(self):
        self.assertEqual(self.submit(user='reader')[0],403)
        self.assertEqual(self.work.post({},'alice',{'X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'cross-site'})[0],403)
        self.assertEqual(self.work.get({},'')[0],401)
    def test_concurrent_same_selection_one_job(self):
        results=[]
        threads=[threading.Thread(target=lambda i=i:results.append(self.submit(rid='parallel_'+str(i)))) for i in range(8)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(len({r[1]['job_id'] for r in results}),1)
    def test_persistence_and_question_context(self):
        _,j=self.submit();self.work.run_one();report=self.work.get_job('alice',j['job_id'])
        self.assertEqual(report['state'],'completed')
        body={'kind':'question','request_id':'question_123','report_id':j['job_id'],'question':'数据还缺少哪些依据？','ai':True}
        self.assertEqual(self.work.post(body,'bob',HEADERS)[0],404)
        _,q=self.work.post(body,'alice',HEADERS);self.work.run_one()
        self.assertEqual(self.work.get_job('alice',q['job_id'])['state'],'completed')
        self.assertEqual(self.calls[-1]['question'],body['question'])
        fresh=a.Advisor(lambda:CAT,self.read,self.daily,self.work.root,clock=lambda:AT)
        self.assertEqual(fresh.get_job('alice',j['job_id'])['result']['report_id'],j['job_id'])
    def test_source_permission_and_revocation_fail_closed(self):
        _,j=self.submit();self.work.read_range=lambda p:(403,{})
        self.work.run_one();r=self.work.get_job('alice',j['job_id'])
        self.assertEqual(r['error'],'source_permission_denied');self.assertIsNone(r['result']);self.assertEqual(self.calls,[])
        _,j=self.submit(rid='revoke_123');self.work.authorizer=lambda u:False;self.work.run_one()
        self.assertEqual(self.work.get_job('alice',j['job_id'])['state'],'failed')
    def test_model_failure_preserves_fact_report(self):
        self.work.model=lambda p:{'status':'unknown_transport'}
        _,j=self.submit();self.work.run_one();r=self.work.get_job('alice',j['job_id'])
        self.assertEqual(r['state'],'completed');self.assertEqual(r['result']['totals']['orders'],10)
        self.assertEqual(r['result']['ai']['status'],'unknown_transport')
    def test_same_shared_budget_and_unknown_no_retry(self):
        for i in range(3):self.assertEqual(self.daily.bounded_model({'test':i},lambda p:{'status':'unknown_transport'})['status'],'unknown_transport')
        self.assertEqual(self.daily.bounded_model({'test':4},self.model)['status'],'daily_model_limit')
        self.assertEqual(self.daily.bounded_model({'test':0},self.model)['status'],'unknown_transport')
        self.assertEqual(self.calls,[])
    def test_management_client_amount_ignored(self):
        p={'key':'FC27','revenue_usd':999999,'orders':123,'estimated_profit_usd':100,'target_revenue_usd':1000,'missing':[]}
        body={'scope':'management','request_id':'boss_report_123','context':{'period':{'start':'2026-10-12','end':'2026-10-12'},'projects':[p]}}
        captured=[]
        with patch.object(a,'explain_boss',lambda x:captured.append(x) or {'status':'succeeded','text':'核对来源后再作判断。'}):
            code,j=self.work.post_boss(body,'alice',HEADERS);self.assertEqual(code,202);self.work.run_one()
        actual=captured[0]['context']['projects'][0]
        self.assertEqual(actual['revenue_usd'],200);self.assertEqual(actual['orders'],10);self.assertEqual(actual['target_revenue_usd'],1000)
        body['context']['projects'][0]['key']='UNREGISTERED';self.assertEqual(self.work.post_boss(body,'alice',HEADERS)[0],422)

class ResponseValidation(unittest.TestCase):
    def test_supported_reference_only_and_usage(self):
        projected={'facts':[{'ref':'FC27.orders'}]}
        r={'model':m.MODEL,'id':'receipt_123','choices':[{'finish_reason':'stop','message':{'content':json.dumps({'analysis':'缺少对比期间，暂不能判断增长。','suggestion':'先补同口径对比资料。','references':['FC27.orders']},ensure_ascii=False)}}],
           'usage':{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}}
        self.assertEqual(m.validate(r,projected)['tokens'],20)
        r['choices'][0]['message']['content']=json.dumps({'analysis':'销售增长百分之十。','suggestion':'立即调价。','references':['secret.orders']})
        with self.assertRaises(ValueError):m.validate(r,projected)

class HTTPBoundary(unittest.TestCase):
    def test_methods_auth_length_and_content_type(self):
        tree=ast.parse((Path(__file__).parent/'range_api.py').read_text('utf-8'))
        cls=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='Handler')
        space={'BaseHTTPRequestHandler':BaseHTTPRequestHandler,'urlsplit':urlsplit,'parse_qs':parse_qs,'json':json,'re':re,'encoded':lambda p:json.dumps(p).encode(),
               'ADVISOR':type('Fake',(),{'post':lambda s,b,u,h:(403,{'error':'admin_required'})})()}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'handler','exec'),space)
        server=ThreadingHTTPServer(('127.0.0.1',0),space['Handler']);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def call(method,headers={},body='{}',path='/advisor'):
            c=http.client.HTTPConnection(*server.server_address,timeout=3);c.request(method,path,body=body,headers=headers);r=c.getresponse();status=r.status;r.read();c.close();return status
        try:
            self.assertEqual(call('POST'),401)
            self.assertEqual(call('PUT',{'X-Auth-User':'alice'}),405)
            self.assertEqual(call('POST',{'X-Auth-User':'alice','Content-Type':'text/plain'}),415)
            self.assertEqual(call('POST',{'X-Auth-User':'alice','Content-Type':'application/json'},body='x'*16385),413)
            self.assertEqual(call('POST',{'X-Auth-User':'alice','Content-Type':'application/json'}),403)
            self.assertEqual(call('POST',{'X-Auth-User':'alice'},path='/range'),405)
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
