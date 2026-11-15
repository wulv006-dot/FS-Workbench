import importlib.util,json,sys,tempfile
from threading import Lock
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'source'))
with patch.dict(sys.modules,{'management_config_store':SimpleNamespace(
 load_active=lambda path:json.loads(Path(path).read_text(encoding='utf8'))
)}):
 import management_v2_runner as runner
import management_facts as facts
from management_facts import fingerprint,stable
real_collect=runner.collect
real_read_query=facts.read_query

with tempfile.TemporaryDirectory(prefix='management-november-test-') as temp:
 root=Path(temp);day='2026-11-03';target=ROOT/'source/targets.json'
 journal=root/'journal'/(day+'.json');journal.parent.mkdir()
 old={'phase':'completed','status':'facts_ready','dataScope':'all-websites-v1','targetVersion':'old-october','fact_status':'available','snapshotId':'old'}
 journal.write_text(json.dumps(old),encoding='utf8')
 invoked=[]
 def collect(now,data,reader,**kw):
  invoked.append(data['period'])
  return {'snapshotId':'management-'+'a'*24,'status':'available','validUntil':'2026-11-04T00:00:00+08:00'}
 runner.collect=collect
 now=lambda:datetime(2026,11,3,16,tzinfo=timezone(timedelta(hours=8)))
 kwargs=dict(manual=True,root=root,public=root/'public.json',status=root/'status.json',targets=target,reader=lambda x:None,clock=now)
 result=runner.run(**kwargs)
 assert result['status']=='facts_ready' and invoked==['2026-11']
 assert result['targetVersion']==fingerprint(json.loads(target.read_text(encoding='utf8')))
 history=list((root/'journal/history').glob('*.json'));assert len(history)==1 and json.loads(history[0].read_text())==old
 assert runner.run(**kwargs)['status']=='already_completed' and len(invoked)==1
 earlier=json.loads(journal.read_text(encoding='utf8'))
 earlier.pop('factsRevision')
 journal.write_text(json.dumps(earlier),encoding='utf8')
 assert runner.run(**kwargs)['factsRevision']==runner.FACTS_REVISION
 assert len(invoked)==2
 assert any(json.loads(p.read_text())==earlier for p in (root/'journal/history').glob('*.json'))
print(json.dumps({'platform':sys.platform,'python':sys.version.split()[0],'same_day_target_change':'passed','old_journal_preserved':'passed','same_version_idempotency':'passed','native_flock':'passed'}))

# Keep the real collector/runner/publication; simulate only source replies and elapsed time.
runner.collect=real_collect
with tempfile.TemporaryDirectory(prefix='management-deadline-test-') as temp:
 root=Path(temp);target=ROOT/'source/targets.json';public=root/'public.json'
 public.write_text('{"snapshotId":"previous-valid"}',encoding='utf8')
 config=json.loads(target.read_text(encoding='utf8'))
 components={key for g in config['overview']['games'] for key in config['models'][g['profile']].get('components',[g['profile']])}
 elapsed=[0.0];seen=set();guard=Lock()
 def read_month(path):
  q={k:v[0] for k,v in parse_qs(urlsplit(path).query).items()}
  assert q['start']=='2026-11-01' and q['end']=='2026-11-02','expired history must not issue source requests'
  with guard:
   seen.add(q['profile'])
   if seen==components:elapsed[0]+=61
  period={'start':'2026-11-01 00:00','end':'2026-11-03 00:00'}
  metric=lambda value,unit:{'status':'available','value':value,'unit':unit}
  admin={'status':'available','normalisedScope':'all-websites','period':period,
   'filters':{'site':'','date':list(period.values()),'pay_status':1,'order_status':''},
   'metrics':{'revenueUsd':metric(100,'USD'),'orders':metric(1,'orders'),'newCustomers':metric(1,'people'),'repeatRatePct':metric(70,'percent'),'fulfillmentRatePct':metric(90,'percent')}}
  order={'status':'available','normalisedScope':'all-websites','period':period,'currency':'USD','metrics':{'profitMarginPct':metric(25,'percent')}}
  return {'http_status':200,'body':{'status':'available','scopeContractId':facts.SOURCE_CONTRACT,
   'query':dict(q,timezone='Asia/Shanghai',period=period),
   'sources':{'Admin':{'status':'available'},'Order':{'status':'available'}},
   'profile':{'key':q['profile'],'supplement':admin,'primary':order}}}
 def query_with_clock(*args,**kwargs):
  return real_read_query(*args,**kwargs,monotonic=lambda:elapsed[0])
 with patch.object(facts,'time',SimpleNamespace(monotonic=lambda:elapsed[0])),patch.object(facts,'read_query',query_with_clock):
  result=runner.run(manual=True,root=root,public=public,status=root/'status.json',targets=target,reader=read_month,clock=now,budget=60)
 assert result['status']=='facts_ready',result
 published=json.loads(public.read_text(encoding='utf8'))
 assert seen==components and len(published['projects'])==25
 assert all(p['month']['status']=='available' and p['month']['values']['rev'] is not None for p in published['projects'])
 assert sum(p['month']['values']['rev'] for p in published['projects'])==2600
 gta=next(p for p in published['projects'] if p['profile']=='GTA_5_6')
 assert gta['month']['values']['rev']==200
 for field,period in [('yesterday',{'start':'2026-11-02','end':'2026-11-02'}),('previousWeek',{'start':'2026-10-26','end':'2026-11-01'})]:
  assert gta[field]['period']==period and gta[field]['status']=='unavailable'
  assert gta[field]['values']['rev'] is None
  assert all(c['period']==period and c['error']=='collection_deadline' for c in gta[field]['components'])
 assert all(d['rev'] is None and d['status']=='unavailable' for d in gta['daily'])
 assert json.loads((root/'facts'/(published['snapshotId']+'.json')).read_text(encoding='utf8'))==published
print(json.dumps({'history_deadline_preserves_months':'passed','real_collect_and_runner':'passed','published_projects':25,'source_components':len(components),'expired_history_periods':'passed','missing_not_zero':'passed'}))
