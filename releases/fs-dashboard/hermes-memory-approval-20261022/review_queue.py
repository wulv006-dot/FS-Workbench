"""Root-side Codex review entry. Never mounted into a Hermes container."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from reviewed_skills import approved_index

ROOT = Path('/var/lib/fs-hermes-memory-approval')
CONTAINER = 'fs-hermes-desktop'
SKILL_HELPERS = Path(__file__).with_name('reviewed_skills.py').read_text(encoding='utf-8')
HEADER = """
import json,hashlib,sys,sqlite3,os,time
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,'/opt/hermes')
from tools import write_approval as wa
from tools.memory_tool import load_on_disk_store,apply_memory_pending
digest=lambda x:hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
filesha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
"""
LIST = """
native=[]
for r in wa.list_pending(wa.MEMORY):
 p=r['payload'];target=('/fs/desktop-business-context.md' if p.get('target')=='business_context' else '/profile/memories/'+('USER.md' if p.get('target')=='user' else 'MEMORY.md'))
 native.append(dict(id='native:'+r['id'],record=r,sha256=digest(r),target_sha256=filesha(target)))
db=sqlite3.connect('file:/fs/tasks.sqlite3?mode=ro',uri=True);db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
experiences=[]
for r in db.execute("SELECT v.*,coalesce(r.state,'pending') state FROM experience_versions v LEFT JOIN experience_releases r ON r.experience=v.id WHERE v.owner='wulv' AND (r.seq IS NULL OR r.seq=(SELECT max(x.seq) FROM experience_releases x WHERE x.experience=v.id)) AND (r.state IS NULL)"):
 r=dict(r);r['content']=json.loads(r['content']);ev=dict(db.execute('SELECT * FROM learning_events WHERE id=?',(r['event'],)).fetchone());ev['input']=json.loads(ev['input'])
 experiences.append(dict(id='experience:'+r['id'],record=r,source=ev,sha256=digest(r)))
from tools import skill_manager_tool as sm
skills=[skill_candidate(r,sm) for r in wa.list_pending(wa.SKILLS)]
print(json.dumps(dict(native=native,experiences=experiences,skills=skills,memory_gate_enabled=wa.write_approval_enabled(wa.MEMORY),skills_gate_enabled=wa.write_approval_enabled(wa.SKILLS)),ensure_ascii=True))
"""
NATIVE = """
r=wa.get_pending(wa.MEMORY,DATA['id'].split(':')[1])
assert r is not None and digest(r)==DATA['expected_sha'],'candidate_changed'
p=r['payload'];target=('/fs/desktop-business-context.md' if p.get('target')=='business_context' else '/profile/memories/'+('USER.md' if p.get('target')=='user' else 'MEMORY.md'))
assert filesha(target)==DATA['target_sha'],'target_changed'
if DATA['decision']=='reject':
 assert wa.discard_pending(wa.MEMORY,r['id']),'pending_discard_failed'
 result=dict(success=True,applied=False,rejected=True)
elif p.get('action')=='core_compaction':
 from tools.memory_tool import _scan_memory_content
 from utils import atomic_write_text
 assert p.get('target') in ('memory','user') and p['base_sha256']==DATA['target_sha'],'core_base_changed'
 archive=Path('/profile/knowledge/hermes-vault/90_历史')/('MEMORY-before-20261022.md' if p['target']=='memory' else 'USER-before-20261022.md')
 assert filesha(archive)==DATA['target_sha'],'exact_original_archive_required'
 store=load_on_disk_store();new=p['content'];limit=store._char_limit(p['target'])
 assert 0<len(new)<=limit and not _scan_memory_content(new),'core_limit_or_content_scan'
 assert filesha(target)==DATA['target_sha'],'core_base_changed'
 atomic_write_text(Path(target),new,tmp_prefix='.codex_curate_')
 check=load_on_disk_store();assert check._char_count(p['target'])<=limit,'core_readback_limit'
 assert wa.discard_pending(wa.MEMORY,r['id']),'applied_pending_cleanup_failed_inspect_receipt'
 result=dict(success=True,applied=True,after_sha256=filesha(target),characters=len(new),limit=limit)
elif p.get('action')=='business_context_patch':
 assert p.get('target')=='business_context' and filesha(target)==p['base_sha256'],'context_base_changed'
 raw=Path(target).read_text();old=p.get('old_text','');new=p['content']
 assert not old or raw.count(old)==1,'context_match_changed'
 updated=raw.replace(old,new,1) if old else raw.rstrip()+'\\n\\n'+new.strip()+'\\n'
 assert updated.strip(),'refuse_empty_context'
 temp=Path(target).with_name('.codex-memory-'+r['id']+'.tmp')
 original_stat=os.stat(target)
 fd=os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,original_stat.st_mode&0o777)
 os.fchown(fd,original_stat.st_uid,original_stat.st_gid)
 with os.fdopen(fd,'w') as f:f.write(updated);f.flush();os.fsync(f.fileno())
 assert filesha(target)==DATA['target_sha'],'context_base_changed'
 os.replace(str(temp),target)
 result=dict(success=True,applied=True,after_sha256=filesha(target))
 assert wa.discard_pending(wa.MEMORY,r['id']),'applied_pending_cleanup_failed_inspect_receipt'
else:
 assert p.get('target','memory') in ('memory','user') and p.get('action') in ('add','replace','remove','batch'),'unsupported_native_payload'
 result=apply_memory_pending(p,load_on_disk_store())
 result['applied']=bool(result.get('success'));result['after_sha256']=filesha(target)
 if result.get('success'):assert wa.discard_pending(wa.MEMORY,r['id']),'applied_pending_cleanup_failed_inspect_receipt'
print(json.dumps(result,ensure_ascii=True))
"""
EXPERIENCE = """
sys.path.insert(0,'/fs-source')
import learning_service,learning_registry
from types import SimpleNamespace
db=sqlite3.connect('/fs/tasks.sqlite3');db.row_factory=sqlite3.Row
key=DATA['id'].split(':')[1]
row=dict(db.execute("SELECT v.*,coalesce(r.state,'pending') state FROM experience_versions v LEFT JOIN experience_releases r ON r.experience=v.id WHERE v.id=? AND v.owner='wulv' AND (r.seq IS NULL OR r.seq=(SELECT max(x.seq) FROM experience_releases x WHERE x.experience=v.id))",(key,)).fetchone());row['content']=json.loads(row['content'])
assert digest(row)==DATA['expected_sha'] and row['state']=='pending' and row['project']=='FS','experience_changed_or_out_of_scope'
now=datetime.now(timezone.utc)
manifest=learning_registry.manifest(db,'wulv','FS',now)
assert manifest['sha256']==DATA['target_sha'],'experience_manifest_changed'
db.close()
def connect():
 db=sqlite3.connect('/fs/tasks.sqlite3');db.row_factory=sqlite3.Row;return db
service=SimpleNamespace(authorizer=lambda user:user=='wulv',clock=lambda:now,tasks=SimpleNamespace(db=connect))
code,result=learning_service.handle(service,'wulv',dict(kind='learning',action='publish' if DATA['decision']=='approve' else 'revoke',id=key,expected_manifest=DATA['target_sha'],reason='Codex delegated review: '+DATA['reason']))
print(json.dumps(dict(success=code==200,applied=code==200,status_code=code,result=result),ensure_ascii=True))
"""
MANIFEST = """
sys.path.insert(0,'/fs-source');import learning_registry
db=sqlite3.connect('file:/fs/tasks.sqlite3?mode=ro',uri=True);db.row_factory=sqlite3.Row
# manifest() calls CREATE IF NOT EXISTS even for reads; read its frozen algorithm without any schema mutation.
items=[]
from pilot import digest as fsdigest
for r in db.execute("SELECT v.id,v.content,v.content_hash,v.expires_at,r.state FROM experience_versions v JOIN experience_releases r ON r.experience=v.id WHERE v.owner='wulv' AND v.project='FS' AND r.seq=(SELECT max(x.seq) FROM experience_releases x WHERE x.experience=v.id) ORDER BY v.id"):
 if r['state']=='published' and learning_registry.instant(r['expires_at'])>datetime.now(timezone.utc):
  content=json.loads(r['content']);assert fsdigest(content)==r['content_hash']
  items.append(dict(id=r['id'],sha256=r['content_hash'],expires_at=r['expires_at'],content=content))
print(json.dumps(dict(sha256=fsdigest(dict(contract=learning_registry.CONTRACT,owner='wulv',project='FS',experiences=items))),ensure_ascii=True))
"""
SNAPSHOT = """
import base64
r=wa.get_pending(wa.MEMORY,DATA['id'].split(':')[1]);assert r is not None and digest(r)==DATA['expected_sha']
p=r['payload'];target=('/fs/desktop-business-context.md' if p.get('target')=='business_context' else '/profile/memories/'+('USER.md' if p.get('target')=='user' else 'MEMORY.md'))
assert filesha(target)==DATA['target_sha']
print(json.dumps(dict(path=target,sha256=filesha(target),bytes_base64=base64.b64encode(Path(target).read_bytes()).decode()),ensure_ascii=True))
"""
SKILL = """
from tools import skill_manager_tool as sm
print(json.dumps(apply_review(DATA,sm,wa),ensure_ascii=True))
"""
SKILL_SNAPSHOT = """
from tools import skill_manager_tool as sm
r=wa.get_pending(wa.SKILLS,DATA['id'].split(':')[1])
assert r is not None and digest(r)==DATA['expected_sha'],'candidate_changed'
candidate=skill_candidate(r,sm)
assert candidate['target_sha256']==DATA['target_sha'],'skill_target_changed'
if 'validation_error' in candidate:
 assert DATA['decision']=='reject','unsafe_skill_approval'
 print(json.dumps(dict(validation_error=candidate['validation_error']),ensure_ascii=True))
else:
 snapshot=target_snapshot(r['payload'],sm,backup=True)
 assert snapshot['sha256']==DATA['target_sha'],'skill_target_changed'
 print(json.dumps(snapshot,ensure_ascii=True))
"""
SKILL_INSPECT = """
from tools import skill_manager_tool as sm
r=wa.get_pending(wa.SKILLS,DATA['candidate_id'].split(':')[1])
packages=[package(sm._skills_dir(),p) for p in DATA['paths']]
print(json.dumps(dict(pending_exists=r is not None,pending_sha256=digest(r) if r else None,
 packages=packages,target_sha256=digest(dict(contract=TARGET_CONTRACT,packages=[dict(path=p['path'],sha256=p['sha256']) for p in packages]))),ensure_ascii=True))
"""


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


def validate_decision(d):
    if not re.fullmatch(r'((native|skill):[a-f0-9]{8}|experience:[a-f0-9]{64})',d.get('id','')):
        raise ValueError('candidate_id')
    if d.get('decision') not in ('approve','reject'):
        raise ValueError('decision')
    for k in ('expected_sha','target_sha'):
        if not re.fullmatch('[a-f0-9]{64}',d.get(k,'')):raise ValueError(k)
    if not 8<=len(d.get('reason','').strip())<=850 or not d.get('evidence','').strip():
        raise ValueError('review_reason_and_evidence_required')
    return d


def run(code,data=None):
    script=HEADER+'\n'+SKILL_HELPERS+'\nDATA=json.loads('+repr(json.dumps(data or {},ensure_ascii=True))+')\n'+code
    result=subprocess.run(['docker','exec','-i',CONTAINER,'/opt/hermes/.venv/bin/python','-'],input=script,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=90)
    if result.returncode:raise RuntimeError('container_operation_failed: '+result.stderr[-2000:])
    return json.loads(result.stdout)


def save(path,value):
    temp=path.with_name(path.name+'.tmp')
    with temp.open('w',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.chmod(str(temp),0o600);os.replace(str(temp),str(path))


def decision_projection(receipt):
    original=receipt.get('result') or {}
    result={k:original[k] for k in ('success','applied','rejected','status_code','after_sha256','characters','limit','error') if k in original}
    if isinstance(original.get('result'),dict):
        if original['result'].get('sha256'):result['knowledge_sha256']=original['result']['sha256']
        if original['result'].get('error'):result['error']=original['result']['error']
    return dict(request_id=receipt['request_id'],reviewer='Codex',decision=receipt['decision'],status=receipt['status'],created_at=receipt['created_at'],result=result)


def receipts():
    return [json.loads(x.read_text(encoding='utf-8')) for x in ROOT.glob('*.json')
            if re.fullmatch(r'[a-f0-9]{64}\.json',x.name)]


def prior_unknown(rows,candidate_id):
    return any(r.get('decision',{}).get('id')==candidate_id and
               r.get('status') in ('applying','unknown_inspect_before_retry') for r in rows)


def export_reviews():
    rows=receipts()
    index=approved_index(rows)
    save(ROOT/'approved-skills.json',index)
    published=ROOT/'published-skills';versions=published/'versions'
    versions.mkdir(mode=0o700,parents=True,exist_ok=True)
    version=versions/(index['sha256']+'.json')
    if version.exists():
        if json.loads(version.read_text(encoding='utf-8'))!=index:raise ValueError('published_skill_version_conflict')
    else:save(version,index)
    save(published/'index.json',index)
    projection=[decision_projection(row) for row in rows]
    save(Path('/var/lib/fs-hermes-fc/profile/memory-review/approval-receipts.json'),projection)


def main():
    import fcntl
    p=argparse.ArgumentParser();p.add_argument('action',choices=('list','decide','inspect','publish-index'));p.add_argument('--decision-file');p.add_argument('--request-id');a=p.parse_args()
    ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (ROOT/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if a.action=='publish-index':
            export_reviews()
            print(json.dumps(dict(success=True,index=json.loads((ROOT/'approved-skills.json').read_text(encoding='utf-8'))),ensure_ascii=True));return
        if a.action=='inspect':
            if a.decision_file and not a.request_id:
                draft=validate_decision(json.loads(Path(a.decision_file).read_text(encoding='utf-8')))
                if not draft['id'].startswith(('native:','skill:')):raise ValueError('package_inspection_requires_native_candidate')
                print(json.dumps(dict(candidate_id=draft['id'],expected_sha=draft['expected_sha'],
                    snapshot=run(SKILL_SNAPSHOT if draft['id'].startswith('skill:') else SNAPSHOT,draft)),ensure_ascii=True));return
            if not re.fullmatch(r'[a-f0-9]{64}',a.request_id or ''):raise ValueError('request_id')
            old=json.loads((ROOT/(a.request_id+'.json')).read_text(encoding='utf-8'))
            result=dict(request_id=old['request_id'],status=old['status'],result=old.get('result'))
            if old['decision']['id'].startswith('skill:'):
                result['observation']=run(SKILL_INSPECT,dict(candidate_id=old['decision']['id'],
                    paths=[p['path'] for p in old.get('backup',{}).get('snapshots',[])]))
            print(json.dumps(result,ensure_ascii=True));return
        if a.action=='list':
            result=run(LIST);result['experience_manifest']=run(MANIFEST)['sha256']
            for group in ('native','experiences','skills'):
                for item in result[group]:
                    item['previous_reviews']=[dict(request_id=r['request_id'],decision=r['decision'],status=r['status'],result=r.get('result')) for r in receipts() if r.get('decision',{}).get('id')==item['id']]
            print(json.dumps(result,ensure_ascii=True));return
        d=validate_decision(json.loads(Path(a.decision_file).read_text(encoding='utf-8')))
        request_id=hashlib.sha256(canonical(d)).hexdigest();receipt_path=ROOT/(request_id+'.json')
        if receipt_path.exists():
            old=json.loads(receipt_path.read_text(encoding='utf-8'));print(json.dumps(dict(request_id=request_id,status=old['status'],result=old.get('result')),ensure_ascii=True));return
        if prior_unknown(receipts(),d['id']):raise RuntimeError('prior_unknown_inspect_original_request_no_replay')
        queue=run(LIST);group=queue['native'] if d['id'].startswith('native:') else queue['skills'] if d['id'].startswith('skill:') else queue['experiences']
        candidate=next((x for x in group if x['id']==d['id']),None)
        assert candidate is not None and candidate['sha256']==d['expected_sha'],'candidate_changed'
        if d['id'].startswith('experience:'):assert run(MANIFEST)['sha256']==d['target_sha'],'manifest_changed'
        else:assert candidate['target_sha256']==d['target_sha'],'target_changed'
        receipt=dict(request_id=request_id,reviewer='Codex',delegated_by='wulv',decision=d,candidate=candidate,status='applying',created_at=time.time())
        if d['id'].startswith('native:'):receipt['backup']=run(SNAPSHOT,d)
        elif d['id'].startswith('skill:'):receipt['backup']=run(SKILL_SNAPSHOT,d)
        save(receipt_path,receipt)
        try:
            result=run(NATIVE if d['id'].startswith('native:') else SKILL if d['id'].startswith('skill:') else EXPERIENCE,d)
            receipt.update(status=('completed' if result.get('success') else 'blocked_not_applied'),result=result,completed_at=time.time())
            save(receipt_path,receipt)
        except Exception as e:
            receipt.update(status='unknown_inspect_before_retry',error_type=type(e).__name__);save(receipt_path,receipt);raise
        # A failed projection must not turn a durably known application into an unknown replay.
        export_reviews()
        print(json.dumps(dict(request_id=request_id,status=receipt['status'],result=result),ensure_ascii=True))


if __name__=='__main__':main()
