import unittest,copy
from datetime import date,timedelta
from fc_category_contract import compact,analysis,cycle_requests,merge_daily,cycle_analysis,type_breakdown,TYPES

day='2026-10-03';period={'start':day+' 00:00','end':'2026-10-04 00:00'}
def record(tid='',orders=100,sales=1000,margin=20):
 return {'status':'available','period':period,'filters':{'gid':'1322','tid':tid,'aid':'0','status':''},'orders':orders,'revenueUsd':sales,'capturedAt':'2026-10-04T00:00:00Z','metrics':{'averageOrderUsd':{'value':sales/orders if orders else None},'profitMarginPct':{'value':margin}},'rows':[{'date':day,'orders':orders,'amount':sales}]}
class Tests(unittest.TestCase):
 def test_native_rates_negative_not_averaged(self):
  records={key:record(tid,10,100,-12 if key=='items' else 50) for key,tid,_ in TYPES};a=analysis(record(margin=17),records,{k:k for k,_,_ in TYPES},period)
  self.assertEqual(a['categories'][1]['profitMarginPct'],-12);self.assertEqual(a['totals']['profitMarginPct'],17)
 def test_partial_missing_is_not_zero(self):
  a=analysis(record(),{'coins':record('1')},{k:k for k,_,_ in TYPES},period)
  self.assertEqual(a['status'],'partial');self.assertIsNone(a['categories'][1]['revenueUsd']);self.assertEqual(a['shareStatus'],'incomplete')
 def test_zero_denominator(self):
  rows={k:record(t,0,0,None) for k,t,_ in TYPES};a=analysis(record(orders=0,sales=0,margin=None),rows,{k:k for k,_,_ in TYPES},period)
  self.assertEqual(a['shareStatus'],'not_computable')
 def test_inconsistent_category_amount_not_clamped(self):
  rows={k:record(t,10,500) for k,t,_ in TYPES};a=analysis(record(sales=1000),rows,{k:k for k,_,_ in TYPES},period)
  self.assertEqual(a['otherRevenueUsd'],-500);self.assertEqual(a['shareStatus'],'incomplete')
 def test_finite_values(self):self.assertIsNone(compact(record(margin=float('nan')))['profitMarginPct'])
 def test_unknown_raw_type_preserved_unmapped(self):
  r=record();r['charts']=[{'title':['产品类型'],'series':[{'data':[{'type':'55','name':'unverified name','count':2,'value':'17.5'}]}]}]
  row=type_breakdown(r)[0];self.assertEqual(row['rawTypeId'],'55');self.assertEqual(row['rawName'],'unverified name');self.assertEqual(row['mapping'],'unmapped')
 def test_bounded_initial_daily_backfill(self):
  r=cycle_requests(date(2026,10,4),'2026-07-06 00:00','2026-10-04 13:19',None)
  self.assertEqual(len(r),10);self.assertEqual(len([x for x in r if x['key'].startswith('daily:')]),6)
 def test_completed_backfill_only_refreshes_yesterday(self):
  previous={'dailyMetrics':{}}
  for n in range(1,8):
   d=(date(2026,10,4)-timedelta(days=n)).isoformat();previous['dailyMetrics'][d]={}
   for key,tid,_ in TYPES:
    r=record(tid);r['period']={'start':d+' 00:00','end':(date.fromisoformat(d)+timedelta(days=1)).isoformat()+' 00:00'};previous['dailyMetrics'][d][key]=compact(r)
  self.assertEqual(len(cycle_requests(date(2026,10,4),'2026-07-06 00:00','2026-10-04 13:19',previous)),7)
 def test_daily_uses_same_range_and_ids(self):
  rows={'daily:FC27:'+day+':coins':record('1',margin=-7)};result=merge_daily(None,rows,date(2026,10,4));self.assertEqual(result[day]['coins']['profitMarginPct'],-7)
  rows[next(iter(rows))]['filters']['aid']='21946';self.assertEqual(merge_daily(None,rows,date(2026,10,4)),{})
 def test_failed_refresh_keeps_good_native_day(self):
  old=merge_daily(None,{'daily:FC27:'+day+':coins':record('1',margin=-7)},date(2026,10,4));fresh=merge_daily({'dailyMetrics':old},{'daily:FC27:'+day+':coins':{'status':'unavailable'}},date(2026,10,4));self.assertEqual(fresh,old)
 def test_no_customer_allocation_or_quantity(self):
  a=analysis(record(),{k:record(t) for k,t,_ in TYPES},{k:k for k,_,_ in TYPES},period)
  self.assertTrue(a['noCustomerAllocation']);self.assertNotIn('newCustomers',a['categories'][0]);self.assertIn('SKU销售数量',a['missingFields'])
 def test_old_good_category_period_retained_on_failure(self):
  primary={'FC27:today':record(),'FC27:all':record(),'FC27:coins':record('1'),'FC27:items':record('2')}
  old=analysis(record(),{k:record(t) for k,t,_ in TYPES},{k:k for k,_,_ in TYPES},period)
  now=cycle_analysis(primary,{},date(2026,10,4),old);self.assertEqual(now['lastGood']['period'],period);self.assertEqual(now['status'],'partial')
if __name__=='__main__':unittest.main()
