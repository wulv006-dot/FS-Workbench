"""Read-only integration probe; prints coverage and counts, not raw business rows."""
from pathlib import Path
import sys,json
sys.path[:0]=[str(Path(__file__).parent/'probe-source'),'/opt/mmoexp-marketing/details']
from collect_details import Reader
from detail_model import make_period
r=Reader();reports={};results=[];start=end='2026-10-17'
try:
 r.ga_fields()
 for source,resource,names in [('ga4','541418940',('landing_country','landing_source')),('gsc','sc-domain:mmoexp.com',('page_country',)),('ads','1430398974',('country_campaign',))]:
  if source=='ads':r.ads_metadata(resource)
  for name in names:
   try:
    value=r.ga(name,start,end) if source=='ga4' else r.gsc(name,start,end) if source=='gsc' else r.ads(resource,name,start,end)
    value.update(source=source,resource=resource,report=name,start_date=start,end_date=end)
    reports[(source,resource,name)]=value
    results.append({'source':source,'report':name,'status':'available','rows':len(value['rows']),'quality':value['quality']})
   except Exception as exc:results.append({'source':source,'report':name,'status':'failed','error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__})
 p=make_period(start,end,reports)
 print(json.dumps({'period':[start,end],'checks':results,'game_contract':p['game_projection_version'],'requests':r.calls},ensure_ascii=False))
finally:r.close()
