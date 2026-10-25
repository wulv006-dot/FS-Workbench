import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from datetime import datetime, date, timedelta

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
import management_facts as m

def sample(profile='FC27',start='2026-10-01',end='2026-10-24'):
    period={'start':start+' 00:00','end':(date.fromisoformat(end)+timedelta(days=1)).isoformat()+' 00:00'}
    field=lambda value,unit:{'status':'available','value':value,'unit':unit}
    admin={'status':'available','period':period,'normalisedScope':'all-websites','filters':{'site':'','date':list(period.values())},
           'metrics':{'revenueUsd':field(1200,'USD'),'orders':field(12,'orders'),'newCustomers':field(3,'people'),'repeatRatePct':field(70,'percent'),'fulfillmentRatePct':field(90,'percent')},
           'dimensions':{'channels':[{'code':'www.mmoexp.com','revenueUsd':10,'orders':1},{'code':'satellite','revenueUsd':1190,'orders':11}]}}
    order={'status':'available','period':period,'currency':'USD','normalisedScope':'all-websites','metrics':{'profitMarginPct':field(25,'percent')}}
    if profile=='RS':
        selection=dict(rs_site='all',rs_server='all',rs_category='all')
        admin.update(normalisedScope='rs-selected',rsSelection=selection)
        order.update(currency='CNY',sourceContract='order-shipping-rs-v1',rsSelection=selection,filters={'source[]':''})
    return {'status':'available','scopeContractId':'admin-main-order-labelled-supplement-v1','query':{'start':start,'end':end,'site':'全部网站' if profile=='RS' else 'www.mmoexp.com','period':period,'profile':profile,'timezone':'Asia/Shanghai'},
            'sources':{'Admin':{'status':'available'},'Order':{'status':'available'}},'profile':{'key':profile,'supplement':admin,'primary':order}}

class AllSites(unittest.TestCase):
    def test_native_totals_replace_main_channel_for_every_game(self):
        for profile in ('FC27','RS','D4','MMOEXP'):
            row=m.project_summary(sample(profile),profile,'2026-10-01','2026-10-24')
            self.assertEqual(row['values'],dict(rev=1200,ord=12,prof=300,new=3,aov=100,rep=70,ful=90,mar=25))
            self.assertEqual(row['dataScope'],m.DATA_SCOPE)
            self.assertIn('预估非实结',row['notes']['prof'])

    def test_scope_date_currency_and_permission_boundaries(self):
        for key,value in [('key','D4')]:
            d=sample();d['profile'][key]=value
            with self.assertRaises(ValueError):m.project_summary(d,'FC27','2026-10-01','2026-10-24')
        for mutation in ('site','date','unit','scope'):
            d=sample();a=d['profile']['supplement']
            if mutation=='site':a['filters']['site']='www.mmoexp.com'
            elif mutation=='date':a['filters']['date'][0]='2026-09-01 00:00'
            elif mutation=='unit':a['metrics']['revenueUsd']['unit']='CNY'
            else:a['normalisedScope']='main'
            with self.assertRaises(ValueError):m.project_summary(d,'FC27','2026-10-01','2026-10-24')
        d=sample('RS');d['profile']['primary']['sourceContract']='unknown'
        self.assertIsNone(m.project_summary(d,'RS','2026-10-01','2026-10-24')['values']['prof'])
        d=sample();d['sources']['Admin']['status']='denied'
        self.assertIsNone(m.project_summary(d,'FC27','2026-10-01','2026-10-24')['values']['rev'])

    def test_retained_same_period_and_missing_not_zero(self):
        d=sample('RS');d['stale']=True;d['sources']['Admin'].update(status='pending',capturedAt='2026-10-25T00:35:00+08:00')
        d['sources']['Order']['capturedAt']='2026-10-25T00:35:00+08:00'
        row=m.project_summary(d,'RS','2026-10-01','2026-10-24')
        self.assertEqual(row['values']['rev'],1200);self.assertEqual(row['freshness'],'retained')
        d['profile']['supplement']['metrics']['revenueUsd']['value']=None
        row=m.project_summary(d,'RS','2026-10-01','2026-10-24')
        self.assertIsNone(row['values']['prof']);self.assertIsNone(row['values']['rev'])

    def test_pending_cost_still_waits_but_daily_does_not(self):
        d=sample();d['profile']['primary']['status']='pending';clock=[0];calls=[]
        def reader(path):
            calls.append(path);return {'http_status':200,'body':d if len(calls)==1 else sample()}
        row=m.read_query(reader,'FC27','2026-10-01','2026-10-24',12,sleep=lambda n:clock.__setitem__(0,clock[0]+n),monotonic=lambda:clock[0])
        self.assertEqual(row['values']['prof'],300);self.assertEqual(len(calls),2)
        calls.clear();row=m.read_query(reader,'FC27','2026-10-01','2026-10-24',12,required=('rev','ord'),sleep=lambda n:None,monotonic=lambda:0)
        self.assertEqual(len(calls),1);self.assertIsNone(row['values']['prof'])

    def test_old_main_cache_never_used_and_targets_unchanged(self):
        from urllib.parse import urlsplit,parse_qs
        calls=[]
        def reader(path):
            q={k:v[0] for k,v in parse_qs(urlsplit(path).query).items()};calls.append(q)
            return {'http_status':200,'body':sample(q['profile'],q['start'],q['end'])}
        targets={'period':'2026-10','overview':{'games':[dict(profile='RS',name='RuneScape',grp='综合',owner='原负责人')]},'models':{'RS':{'l1':[dict(id='rev',val=5000)],'l2':[],'weeks':[]}}}
        original=copy.deepcopy(targets);cache={m.fingerprint(['RS','2026-10-01','2026-10-01','admin-main-order-labelled-supplement-v1']):{'values':dict(rev=1)}}
        data=m.collect(datetime(2026,10,2,15,tzinfo=m.SH),targets,reader,cache=cache)
        self.assertEqual(data['projects'][0]['yesterday']['values']['rev'],1200)
        self.assertEqual(data['projects'][0]['owner'],'原负责人');self.assertEqual(targets,original)
        self.assertEqual(data['dataScope'],m.DATA_SCOPE)

    def test_manual_scope_migration_preserves_original_receipt(self):
        if sys.platform=='win32':
            self.skipTest('POSIX locks and directory fsync verified on Linux')
        import management_v2_runner as runner
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);journal=root/'journal/2026-10-25.json';journal.parent.mkdir()
            old=b'{"phase":"completed","status":"facts_ready","snapshotId":"original-main"}'
            journal.write_bytes(old);targets=root/'targets.json';targets.write_text('{}')
            original=runner.collect
            runner.collect=lambda *a,**k:dict(contract=m.CONTRACT,dataScope=m.DATA_SCOPE,snapshotId='management-'+'a'*24,status='available',validUntil='2026-10-26T00:00:00+08:00')
            try:
                args=dict(root=root,public=root/'public.json',status=root/'status.json',targets=targets,clock=lambda:datetime(2026,10,25,15,tzinfo=m.SH),reader=lambda _:None)
                self.assertEqual(runner.run(**args)['status'],'outside_nightly_window')
                self.assertEqual(runner.run(manual=True,**args)['status'],'facts_ready')
                self.assertEqual(next((root/'journal/history').iterdir()).read_bytes(),old)
                self.assertEqual(runner.run(manual=True,**args)['status'],'already_completed')
                self.assertEqual(json.loads(journal.read_text())['ai_status'],'pending_hermes')
                journal.write_text('{"phase":"collecting","status":"running"}')
                self.assertEqual(runner.run(manual=True,**args)['status'],'original_operation_unreconciled')
            finally:runner.collect=original

if __name__=='__main__':unittest.main()
