import copy,json,sys,unittest,tempfile
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import business_shipping as s
import live_summary as summary
import profit_daily as daily
import daily_archive as archive

class Shipping(unittest.TestCase):
 def setUp(self):
  self.q=dict(profile='FC27',profit_site='main',profit_category='-1',period=dict(start='2026-10-23 00:00',end='2026-10-24 00:00'))
  self.raw=dict(filters=s.filters(self.q),headers=['游戏','￥销售总额','￥采购总额','利润率','订单总数','交易总数'],rows=[['1322 | FC27','180004.99','125547.42','30.25%','383','383']])
 def test_actual_id_not_admin_id(self):self.assertEqual(s.filters(dict(self.q,profile='AION2'))['gid'],'826');self.assertEqual(s.filters(self.q)['gid'],'1322')
 def test_amount_not_cross_currency(self):
  v=s.project(self.raw,self.q);self.assertEqual(v['metrics']['profitCny']['value'],54457.57);self.assertEqual(v['metrics']['profitMarginPct']['value'],30.25);self.assertNotIn('revenueUsd',v['metrics'])
 def test_global_weighted_not_average(self):
  self.q['profile']='MMOEXP';self.raw['filters']=s.filters(self.q);self.raw['rows']=[['1322 | FC','100','50','50%','1','1'],['456 | D4','900','810','10%','2','2']]
  v=s.project(self.raw,self.q);self.assertEqual(v['metrics']['profitMarginPct']['value'],14);self.assertEqual(v['metrics']['profitCny']['value'],140)
 def test_duplicate_wrong_game_or_total(self):
  for rows in [self.raw['rows']*2,[['456 | D4','100','50','50%','1','1']],[['合计','1','1','0%','1','1']]]:
   with self.assertRaises(ValueError):s.project(dict(self.raw,rows=rows),self.q)
 def test_bad_filters_unit_or_ratio(self):
  for key,value in [('gid','1327'),('cid','1'),('source[]','')]:
   r=copy.deepcopy(self.raw);r['filters'][key]=value
   with self.assertRaises(ValueError):s.project(r,self.q)
  r=copy.deepcopy(self.raw);r['headers'][1]='$销售总额'
  with self.assertRaises(ValueError):s.project(r,self.q)
  r=copy.deepcopy(self.raw);r['rows'][0][3]='80%'
  with self.assertRaises(ValueError):s.project(r,self.q)
 def test_empty_and_loss(self):
  v=s.project(dict(self.raw,rows=[]),self.q);self.assertEqual(v['metrics']['profitCny']['value'],0);self.assertIsNone(v['metrics']['profitMarginPct']['value'])
  v=s.project(dict(self.raw,rows=[['1322 | FC','100','120','-20%','1','1']]),self.q);self.assertEqual(v['metrics']['profitCny']['value'],-20)
  v=s.project(dict(self.raw,rows=[['1322 | FC','0','5','0%','1','1']]),self.q);self.assertEqual(v['metrics']['profitCny']['value'],-5);self.assertIsNone(v['metrics']['profitMarginPct']['value'])
 def test_invalid_boundary(self):
  for q in [dict(self.q,profile='UNKNOWN'),dict(self.q,profit_site='evil'),dict(self.q,profit_category='<script>')]:
   with self.assertRaises(ValueError):s.filters(q)
 def test_day_scope_and_old_cache(self):
  r=s.project(self.raw,self.q);r.update(date='2026-10-23',capturedAt='2026-10-24T08:00:00+00:00')
  expected={'FC27':dict(sites='www.mmoexp.com',gid='1322',tid='-1',status='-1',aid='0',delivery='shipping')}
  v=daily.normalise(r,expected);daily.validate_row(v,expected);self.assertEqual(v['profileKey'],'FC27');self.assertEqual(v['profitCny'],54457.57)
  v['sourceContract']='old-source'
  with self.assertRaises(ValueError):daily.validate_row(v,expected)
 def test_query_cache_scope(self):
  def q(**kw):return summary.query({k:[v] for k,v in dict(profile='FC27',mode='summary',start='2026-10-23',end='2026-10-23',**kw).items()},{'FC27':1})
  a=q()
  for b in [q(profit_category='1'),q(profit_site='all')]:self.assertNotEqual(summary.key_of(a),summary.key_of(b));self.assertNotEqual(archive.summary_key(a),archive.summary_key(b))
  self.assertEqual(a['profit_source'],'order-shipping-v1')

class Pool:
 def __init__(self):self.jobs=[]
 def shutdown(self,wait=True):pass
 def submit(self,fn,*args):self.jobs.append((fn,args))
 def drain(self):
  jobs,self.jobs=self.jobs,[]
  for fn,args in jobs:fn(*args)
class ThreeSource(unittest.TestCase):
 def test_shared_pool_admin_independent_and_shipping_denial(self):
  def read(q):return dict(status='available',period=q['period'],capturedAt=datetime.now(timezone.utc).isoformat(),metrics={})
  c=summary.SummaryCache(read,read,{'FC27':('', 'FC')},shipping_read=read);self.addCleanup(c.close)
  self.assertIs(c.pools['Order'],c.pools['Shipping']);c.close();c.pools={'Admin':Pool(),'Order':Pool()};c.pools['Shipping']=c.pools['Order']
  c.close=lambda:None
  q=summary.query({k:[v] for k,v in dict(profile='FC27',mode='summary',start='2026-10-23',end='2026-10-23').items()},{'FC27':1})
  with patch.object(archive,'read',return_value=None),patch.object(archive,'derive_summary',return_value=None),patch.object(archive,'save'):
   self.assertEqual(c.get(q)[0],202);c.pools['Admin'].drain();v=c.get(q)[1];self.assertEqual(v['profile']['shipping']['status'],'pending')
   c.pools['Order'].drain();v=c.get(q)[1];self.assertEqual(v['sources']['Shipping']['status'],'available')
   slot=c.entries[summary.key_of(q)]['Shipping'];slot.update(state='denied',at=c.clock());self.assertEqual(c.get(q)[0],403)
if __name__=='__main__':unittest.main()
