import sys,unittest,copy
from pathlib import Path
from datetime import datetime,date,timedelta,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source/backend'))
from management_facts import project_summary,periods,calculate,numeric,collect,CONTRACT

def sample(profile='FC27',start='2026-10-01',end='2026-10-14'):
 p={'start':start+' 00:00','end':(date.fromisoformat(end)+timedelta(days=1)).isoformat()+' 00:00'}
 metric=lambda v:{'status':'available','value':v}
 a={'status':'available','period':p,'dimensions':{'channels':[{'code':'www.mmoexp.com','revenueUsd':1000,'orders':10}]},'metrics':{'newCustomers':metric(3),'repeatRatePct':metric(70),'fulfillmentRatePct':metric(90)}}
 o={'status':'available','currency':'USD','period':p,'metrics':{'profitMarginPct':metric(25)}}
 return {'status':'available','scopeContractId':'admin-main-order-labelled-supplement-v1','query':{'start':start,'end':end,'site':'www.mmoexp.com','period':p,'profile':profile,'timezone':'Asia/Shanghai'},'sources':{'Admin':{'status':'available'},'Order':{'status':'available'}},'profile':{'key':profile,'supplement':a,'primary':o}}
class Facts(unittest.TestCase):
 def test_admin_main_and_reference_profit(self):
  p=project_summary(sample(),'FC27','2026-10-01','2026-10-14');self.assertEqual(p['values'],dict(rev=1000,ord=10,prof=250,new=3,aov=100,rep=70,ful=90,mar=25));self.assertIn('预估非实结',p['notes']['prof'])
 def test_missing_is_not_zero(self):
  d=sample();d['profile']['supplement']['dimensions']['channels']=[]
  p=project_summary(d,'FC27','2026-10-01','2026-10-14');self.assertIsNone(p['values']['rev']);self.assertIsNone(p['values']['prof'])
 def test_stale_reference_not_used(self):
  d=sample();d['profile']['primary']['stale']=True
  p=project_summary(d,'FC27','2026-10-01','2026-10-14');self.assertEqual(p['values']['rev'],1000);self.assertIsNone(p['values']['mar']);self.assertIsNone(p['values']['prof'])
 def test_mismatched_period_rejected(self):
  for change in ['key','period']:
   d=sample()
   if change=='key':d['profile']['key']='D4'
   else:d['query']['end']='2026-10-13'
   with self.assertRaises(ValueError):project_summary(d,'FC27','2026-10-01','2026-10-14')
 def test_first_day_no_complete_month(self):
  p=periods(date(2026,10,1),'2026-10');self.assertEqual(p['observed'],0);self.assertEqual(p['end'],'2026-09-30')
 def test_expired_target_not_reused(self):
  self.assertFalse(periods(date(2026,11,2),'2026-10')['active'])
 def test_linear_forecast_and_no_zero_division(self):
  p=calculate({'rev':100},{'rev':310},10,31);self.assertEqual(p['forecast']['rev'],310);self.assertEqual(p['remainingDaily']['rev'],10)
  p=calculate({'rev':None},{'rev':310},10,31);self.assertIsNone(p['completion']['rev'])
  p=calculate({'rev':100},{'rev':0},0,31);self.assertIsNone(p['completion']['rev'])
 def test_boolean_and_nonfinite_not_numeric(self):
  for x in [True,False,float('nan'),float('inf'),'100',None]:self.assertFalse(numeric(x))
 def test_nonmain_admin_metrics_labelled_reference(self):
  d=sample();d['profile']['supplement']['dimensions']['channels'].append({'code':'satellite','revenueUsd':200,'orders':2})
  p=project_summary(d,'FC27','2026-10-01','2026-10-14');self.assertEqual(p['values']['rev'],1000);self.assertIn('参考',p['notes']['new'])
 def test_collect_all_core_before_history_and_today_validity(self):
  from urllib.parse import urlsplit,parse_qs
  calls=[]
  def reader(path):
   q={k:v[0] for k,v in parse_qs(urlsplit(path).query).items()};calls.append(q)
   return {'http_status':200,'body':sample(q['profile'],q['start'],q['end'])}
  games=[{'profile':k,'name':k,'grp':'球类','owner':'负责人'} for k in ['FC27','NBA2K27']]
  targets={'period':'2026-10','overview':{'games':games},'models':{k:{'l1':[{'id':'rev','val':3100},{'id':'ord','val':31},{'id':'prof','val':775}],'l2':[{'id':'mar','val':25}],'weeks':[{'id':'w1','lab':'第1周 10/1-10/4','rev':400,'ord':4}]} for k in ['FC27','NBA2K27']}}
  out=collect(datetime(2026,10,3,0,20,tzinfo=timezone(timedelta(hours=8))),targets,reader)
  self.assertEqual(out['contract'],CONTRACT);self.assertEqual(out['businessDate'],'2026-10-03');self.assertEqual(out['validUntil'],'2026-10-04T00:00:00+08:00')
  self.assertEqual({x['profile'] for x in calls[:2]},{'FC27','NBA2K27'});self.assertTrue(all(x['start']=='2026-10-01' and x['end']=='2026-10-02' for x in calls[:2]))
  self.assertEqual(out['projects'][0]['weeks'][0]['actRev'],2000)
  self.assertTrue(out['snapshotId'].startswith('management-'))
if __name__=='__main__':unittest.main()

class SourceWaiting(unittest.TestCase):
 def test_wait_for_order_without_freezing_early_missing_profit(self):
  from management_facts import read_query
  clock=[0];calls=[];partial=sample();partial['profile']['primary']['status']='pending'
  def read(path):calls.append(path);return {'http_status':200,'body':partial if len(calls)==1 else sample()}
  result=read_query(read,'FC27','2026-10-01','2026-10-14',100,sleep=lambda n:clock.__setitem__(0,clock[0]+n),monotonic=lambda:clock[0])
  self.assertEqual(result['values']['prof'],250);self.assertEqual(len(calls),2)
 def test_partial_facts_survive_transport_wait_deadline(self):
  from management_facts import read_query
  clock=[0];calls=[];partial=sample();partial['profile']['primary']['status']='pending'
  def read(path):calls.append(path);return {'http_status':200,'body':partial} if len(calls)==1 else {'http_status':503,'body':{'retryAfterSeconds':20}}
  result=read_query(read,'FC27','2026-10-01','2026-10-14',12,sleep=lambda n:clock.__setitem__(0,clock[0]+n),monotonic=lambda:clock[0])
  self.assertEqual(result['values']['rev'],1000);self.assertIsNone(result['values']['prof']);self.assertEqual(result['status'],'partial');self.assertEqual(clock[0],12)
