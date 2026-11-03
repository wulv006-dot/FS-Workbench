import importlib.util,json,sys,tempfile
from datetime import datetime,timezone,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'source'))
import management_v2_runner as runner
from management_facts import fingerprint,stable

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
print(json.dumps({'platform':sys.platform,'python':sys.version.split()[0],'same_day_target_change':'passed','old_journal_preserved':'passed','same_version_idempotency':'passed','native_flock':'passed'}))
