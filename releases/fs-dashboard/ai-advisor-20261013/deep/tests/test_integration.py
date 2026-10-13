import copy
from datetime import date, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import ai_advisor
from fc_daily import DailyReports
from fc_deep_service import DeepService
from test_deep import AT, fixture, evidence

CAT={'catalogId':'test-catalog','profiles':{'FC27':{'name':'FC27'}},'dashboard':{'groups':[]}}
HEADERS={'X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin'}
SELECT={'scope':'project','project':'FC27','kind':'day','anchor':'2026-10-12'}


class Reader:
    def collect(self,*args):return evidence()
    def collect_bundle(self,*args):
        q,d,c=fixture()
        return evidence(),d,c


class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.daily=DailyReports(None,self.root/'daily',clock=lambda:AT,is_configured=lambda:True,authorizer=lambda user:user=='admin')
        self.calls=[]
        def model(p):
            self.calls.append(p)
            from fc_deep_analysis import fallback
            return dict(fallback(evidence()),status='succeeded',tokens=100,response_id='test-receipt',model='fixture')
        self.deep=DeepService(None,self.daily,self.root/'memory',reader=Reader(),model=model)
        self.daily.deep=self.deep
        self.advisor=ai_advisor.Advisor(lambda:CAT,lambda _:(_ for _ in ()).throw(AssertionError('unexpected_old_source')),self.daily,self.root/'advisor',clock=lambda:AT,authorizer=lambda u:u=='admin',deep=self.deep)

    def test_imports_use_candidate_not_frozen_release(self):
        self.assertIn('deep',str(Path(ai_advisor.__file__)))
        self.assertTrue(hasattr(self.advisor,'memory_action'))

    def test_deep_job_and_idempotent_model_same_pack(self):
        code,job=self.advisor.post({'kind':'report','request_id':'request_test_123','selection':SELECT,'ai':True},'admin',HEADERS)
        self.assertEqual(code,202);self.assertTrue(self.advisor.run_one())
        saved=self.advisor.get_job('admin',job['job_id'])
        self.assertEqual(saved['state'],'completed');self.assertEqual(saved['result']['ai']['status'],'succeeded')
        self.assertEqual(len(saved['result']['deep']['comparisons']),4)
        self.assertEqual(len(self.calls),1)
        self.advisor.post({'kind':'report','request_id':'request_test_123','selection':SELECT,'ai':True},'admin',HEADERS)
        self.assertFalse(self.advisor.run_one());self.assertEqual(len(self.calls),1)
        self.assertIsNone(self.advisor.get_job('other',job['job_id']))

    def test_private_memory_auth_same_origin_and_data_separation(self):
        body={'kind':'memory_add','memory':{'request_id':'memory_test_123','project':'FC27','kind':'target','text':'保持可核查的利润和交付质量。','effective_start':'2026-10-01','effective_end':None}}
        self.assertEqual(self.advisor.post(body,'member',HEADERS)[0],403)
        self.assertEqual(self.advisor.post(body,'admin',dict(HEADERS,**{'Sec-Fetch-Site':'cross-site'}))[0],403)
        self.assertEqual(self.advisor.post(body,'admin',HEADERS)[0],200)
        self.assertEqual(self.advisor.get({'memory':['true']},'other')[1]['contexts'],[])
        self.assertEqual(len(self.advisor.get({'memory':['true']},'admin')[1]['contexts']),1)
        self.assertEqual(self.calls,[])

    def test_model_failure_retains_actions_and_facts(self):
        self.deep.model=lambda _: {'status':'unknown_transport'}
        _,job=self.advisor.post({'kind':'report','request_id':'request_test_123','selection':SELECT,'ai':True},'admin',HEADERS)
        self.advisor.run_one();saved=self.advisor.get_job('admin',job['job_id'])
        self.assertEqual(saved['result']['deep']['decision']['status'],'deterministic')
        self.assertEqual(saved['result']['deep']['decision']['model_status'],'unknown_transport')
        self.assertEqual(saved['result']['totals']['orders'],2)
        with self.daily.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0],1)

    def test_daily_uses_one_deep_bundle_and_legacy_ui_fields(self):
        self.daily.enqueue('2026-10-12','deep_daily_123')
        self.assertTrue(self.daily.run_one());r=self.daily.latest('2026-10-12')
        self.assertIsNotNone(r)
        self.assertEqual(r['main']['orders'],2)
        self.assertEqual(r['ai']['status'],'succeeded')
        self.assertTrue(r['ai']['explanation']);self.assertTrue(r['ai']['next_step'])
        self.assertEqual(r['deep']['plan']['read_start'],'2026-09-12')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.deep.memory.recall('admin',dict(evidence(),plan={'start':'2026-10-13','end':'2026-10-13'}))['observations'],[])

    def test_partial_today_not_remembered_as_complete_day(self):
        e=evidence();e['windows'][0]['complete_days']=False
        self.assertFalse(self.deep.memory.remember('admin','test_report_id',e,{},AT))

    def test_review_does_not_claim_causal_effect(self):
        e=evidence();e['plan']['end']='2026-10-14'
        recalled={'observations':[{'report_id':'old-report','start':'2026-10-10','end':'2026-10-10','main':{'revenue_usd':100},'reviews':[{'verify':{'metric':'revenue_usd','direction':'increase','window_days':3}}]}]}
        out=self.deep.review(e,recalled)
        self.assertFalse(out[0]['implementation_confirmed']);self.assertTrue(out[0]['review_due'])


if __name__=='__main__':unittest.main()
