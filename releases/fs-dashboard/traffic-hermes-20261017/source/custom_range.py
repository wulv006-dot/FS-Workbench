"""Build real arbitrary Google date ranges with existing audited readers."""
from datetime import date,datetime,timezone
from pathlib import Path
import sys,json,urllib.request,urllib.parse
ROOT=Path('/opt/mmoexp-marketing')
sys.path.insert(0,str(ROOT/'details'))

def validate(start,end):
 for value in (start,end):
  if date.fromisoformat(value).isoformat()!=value:raise ValueError('invalid_date')
 if start>end:raise ValueError('invalid_date_order')
 if (date.fromisoformat(end)-date.fromisoformat(start)).days>365:raise ValueError('maximum_366_days')
 return start,end
def collect(start,end,reader,make_period,ga_reports,gsc_reports,customers):
 validate(start,end);reports={};failures=[]
 try:reader.ga_fields()
 except Exception:failures.append({'source':'ga4','report':'metadata','status':'unavailable'})
 for customer in customers:
  try:reader.ads_metadata(customer)
  except Exception:failures.append({'source':'ads','resource':customer,'report':'metadata','status':'unavailable'})
 for source,resource,names in [('ga4','541418940',ga_reports),('gsc','sc-domain:mmoexp.com',gsc_reports)]+[('ads',customer,['total','daily','campaign','campaign_total','ad_group_total']) for customer in customers]:
  for name in names:
   try:
    value=reader.ga(name,start,end) if source=='ga4' else reader.gsc(name,start,end) if source=='gsc' else reader.ads(resource,name,start,end)
    value.update(source=source,resource=resource,report=name,start_date=start,end_date=end,collected_at=datetime.now(timezone.utc).isoformat())
    reports[(source,resource,name)]=value
   except Exception:failures.append({'source':source,'resource':resource,'report':name,'status':'unavailable'})
 period=make_period(start,end,reports);period['isCustomRange']=True
 from traffic_contract import RULE_VERSION
 period['rule_version']=RULE_VERSION
 return {'schemaVersion':1,'status':('partial' if failures else 'available') if reports else 'unavailable','start':start,'end':end,'period':period,'failures':failures,'generatedAt':datetime.now(timezone.utc).isoformat()}
def main():
 from collect_details import Reader,GA_REPORTS,GSC_REPORTS,CUSTOMERS
 from detail_model import make_period
 start,end=validate(*sys.argv[1:3]);reader=Reader()
 try:result=collect(start,end,reader,make_period,GA_REPORTS,GSC_REPORTS,CUSTOMERS)
 finally:reader.close()
 query=urllib.parse.urlencode({'start':start,'end':end})
 try:
  with urllib.request.urlopen('http://127.0.0.1:8767/marketing/summary?'+query,timeout=75) as response:result['businessLinks']=json.load(response)
 except (OSError,ValueError):result['businessLinks']={'status':'unavailable','reason':'Admin关联数据本次不可用，未填零。'}
 print(json.dumps(result,ensure_ascii=False,allow_nan=False))
if __name__=='__main__':main()
