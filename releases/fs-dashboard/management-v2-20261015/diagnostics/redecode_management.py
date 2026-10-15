"""Re-project a completed immutable management output after parser repair.
No model call, no task replay, no edits to original reports or task ledger.
The new public projection is separately backed up with CAS and bound receipts.
"""
import argparse,hashlib,json,sqlite3,sys
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime
sys.path[:0]=['/opt/fs-hermes-fc','/opt/fs-exact-range-20261001']
import management_context as m
from report_artifacts import read_file,directory
p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');a=p.parse_args()
root=Path('/var/lib/fs-hermes-fc/fs')
with sqlite3.connect('file:'+str(root/'tasks.sqlite3')+'?mode=ro',uri=True) as db:
 row=db.execute("SELECT r.id,r.state,r.body,t.id,t.run_id FROM requests r JOIN tasks t ON t.id=r.task_id WHERE r.body LIKE ? ORDER BY r.rowid DESC LIMIT 1",('%经营管理台日更%',)).fetchone()
if not row or row[1]!='COMPLETED':raise ValueError('terminal_request_required')
body=json.loads(row[2]);task=row[3];folder=directory(root,task);meta=json.loads((folder/'metadata.json').read_text());raw=read_file(root,task,'raw');evraw=(folder/'evidence.json').read_bytes()
if meta.get('native_completed') is not True or meta['run_id']!=row[4] or raw['sha256']!=meta['raw_sha256'] or hashlib.sha256(evraw).hexdigest()!=meta['evidence_sha256']:raise ValueError('bound_artifact_required')
facts=m.load(body);book=SimpleNamespace(evidence=json.loads(evraw),capture_id=facts['snapshotId'])
result=m.deliver(raw['content'],book);result['reasoning_effort']=meta['reasoning_effort'];result['management_context']=m.metadata(body)
result['management_context']['evidenceId']=next(k for k,v in book.evidence.items() if v.get('snapshot_id')==facts['snapshotId'] and v.get('project')=='ALL_MANAGEMENT_PROJECTS')
now=datetime.now(m.SH);analysis=m.analysis_from_result(result,facts,task,now)
if analysis['status']!='succeeded':raise ValueError('structured_quality_not_passed:'+','.join(analysis['qualityIssues']))
out={'task':task,'raw_sha256':raw['sha256'],'status':analysis['status'],'actions':len(analysis['actions']),'reasoningEffort':analysis['reasoningEffort'],'modelCalled':False,'originalReportsModified':False,'published':False}
if a.apply:
 current=m.PUBLIC.read_bytes();before=json.loads(current)
 if before.get('analysis',{}).get('taskId')!=task:raise ValueError('newer_task_present')
 archive=m.ROOT/'delivery-revisions'/task;archive.mkdir(parents=True,exist_ok=True)
 backup=archive/'before-management-delivery-v2.json'
 if backup.exists():raise ValueError('revision_already_attempted_read_back_first')
 backup.write_bytes(current);backup.chmod(0o600)
 if m.PUBLIC.read_bytes()!=current:raise ValueError('public_changed')
 out['published']=m.publish(body,result,task,now=now)
 m.atomic_json(archive/'receipt-management-delivery-v2.json',out)
print(json.dumps(out))
