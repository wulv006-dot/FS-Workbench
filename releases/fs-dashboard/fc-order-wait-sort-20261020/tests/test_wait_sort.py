import sys,json,copy,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fc_detail_model import normalize,aggregate
CFG=json.loads(Path(__file__).with_name('config.json').read_text());CFG['trust_customer_flag']=True
NOW=datetime(2026,10,20,1,tzinfo=timezone(timedelta(hours=8)))
def row(n,hours,high=False):
 when=(NOW-timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S') if hours is not None else None
 amount='9999.00' if high else '20.00'
 return normalize(dict(order_no='SYNTH-'+str(n),gid=1327,pay_status=1,site_id=266,amount=amount,amount_usd_format='$ '+amount,uid=1,isNew=1 if high else 0,content='PC coins',paytime=when,timestamp_format=when,status=31,status_format='发货中'),CFG,{266})
def run(rows,**extra):
 ds={'orders':rows,'backlog':rows,'as_of':NOW.isoformat(),'snapshot_id':'synthetic','coverage':{'backlog_status':'available','missing_days':[]},'data_status':'available'}
 q={'start':'2026-01-01','end':'2026-10-20','pool':'current','page':1,**extra}
 return aggregate(ds,q,CFG,NOW)
class Tests(unittest.TestCase):
 def test_shortest_first_not_attention(self):
  d=run([row('old',500,True),row('new',1),row('zero',0)])
  self.assertEqual([x['id'] for x in d['orders']],['SYNTH-zero','SYNTH-new','SYNTH-old'])
  self.assertTrue(d['orders'][-1]['attention']);self.assertEqual(d['list_total'],3)
 def test_unknown_last_stable_ties(self):
  d=run([row('unknown',None),row('b',2),row('a',2)])
  self.assertEqual([x['id'] for x in d['orders']],['SYNTH-a','SYNTH-b','SYNTH-unknown'])
 def test_sort_before_pagination(self):
  rows=[row(i,i) for i in range(23,0,-1)]
  a=run(rows,page=1);b=run(rows,page=2)
  self.assertEqual([x['age_hours'] for x in a['orders']],list(range(1,11)))
  self.assertEqual([x['age_hours'] for x in b['orders']],list(range(11,21)))
  self.assertEqual(a['list_total'],23)
 def test_csv_and_paid_pool_contract(self):
  rows=[row(i,i) for i in range(13,0,-1)]
  d=run(rows,format='csv');self.assertEqual(len(d['orders']),13);self.assertEqual(d['orders'][0]['age_hours'],1)
  d=run(rows,pool='paid');self.assertEqual(d['orders'][0]['id'],'SYNTH-13')
 def test_terminal_not_reintroduced_and_summary_unchanged(self):
  rows=[row(1,4),row(2,8),dict(row(3,1),terminal=True,status='已完成')]
  d=run(rows);self.assertEqual(d['list_total'],2);self.assertEqual(d['backlog_summary']['orders'],2);self.assertEqual(d['backlog_summary']['revenue_usd'],40)
if __name__=='__main__':unittest.main()
