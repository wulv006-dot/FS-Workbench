"""Existing host bridge's bounded PR -> CI -> publisher state machine."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from datetime import datetime,timezone
from urllib.error import HTTPError,URLError
from urllib.parse import quote
from contract import build,require,sha,snapshot,strict_json,verify_candidate
import publication

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from github_api import GitHub
from host import parent_fd

PROFILE=Path('/var/lib/fs-hermes-fc/profile/game-monitor-maintenance')
STATE=Path('/var/lib/fs-hermes-ops/game-monitor')
PREFIX='releases/fs-dashboard/game-monitor-autopublish-20261022/'
TOKEN_FILE='/var/lib/fs-hermes-fc/profile/.config/gh/hosts.yml'
TERMINAL={'published_file_and_route_readback_verified','no_content_change','rolled_back_verified'}

def profile_read(name,optional=False):
    require(re.fullmatch(r'[a-zA-Z0-9_.-]+',name) is not None,'fixed_profile_filename')
    path=PROFILE/name
    try:
        with parent_fd(path) as directory:
            fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=directory)
            with os.fdopen(fd,'rb') as stream:
                info=os.fstat(stream.fileno())
                require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=4*1024*1024,'invalid_profile_payload')
                return stream.read(4*1024*1024+1)
    except FileNotFoundError:
        if optional:return None
        raise

def atomic(path,raw,profile=False):
    if not profile:
        publication.safe(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Parent descriptors bind profile writes even if the container renames a directory.
    with parent_fd(path) as directory:
        temporary='.'+path.name+'.'+str(os.getpid())
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
        try:
            with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path.name,src_dir_fd=directory,dst_dir_fd=directory);os.fsync(directory)
        finally:
            try:os.unlink(temporary,dir_fd=directory)
            except FileNotFoundError:pass

def write(path,value,profile=False):atomic(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode(),profile)

def load(path,default=None):
    try:return strict_json(publication.safe(path).read_bytes())
    except FileNotFoundError:return default

def save(record):
    record['checked_at']=datetime.now(timezone.utc).isoformat()
    write(STATE/'runs'/record['run_id']/'state.json',record);write(STATE/'latest.json',record)
    write(PROFILE/'auto-publish-status.json',record,True)

def export_live():
    path=publication.active();raw=path.read_bytes()
    atomic(PROFILE/'live-index.html',raw,True)
    write(PROFILE/'live-data.json',snapshot(raw),True)
    write(PROFILE/'live-baseline.json',dict(schema=1,sha256=sha(raw),release=path.parent.parent.name,exported_at=datetime.now(timezone.utc).isoformat()),True)

def optional(github,path):
    try:return github.request('GET',path)
    except HTTPError as error:
        if error.code==404:return None
        raise

def candidate_files(record):
    folder=STATE/'runs'/record['run_id']/'candidate'
    verify_candidate(folder)
    return {PREFIX+'candidate/'+name:(folder/name).read_bytes() for name in ('before.html','index.html','request.json','proof.json')}

def check_pr(pr,record):
    require(pr['head']['ref']==record['branch'] and pr['base']['ref']=='main' and pr['head']['repo']['full_name']=='wulv006-dot/FS-Workbench','pr_identity_drift')
    require(pr['head']['sha']==record['pr']['head'],'pr_head_drift')

def open_pr(github,record):
    branch=record['branch']
    existing=optional(github,'/git/ref/heads/'+branch)
    if existing:
        rows=github.request('GET','/pulls?state=all&head='+quote('wulv006-dot:'+branch,safe=''))
        require(len(rows)<=1,'ambiguous_original_pr')
        require(bool(rows),'branch_without_pr_reconcile_required')
        pr=rows[0];require(pr['state']=='open' or pr['merged_at'],'original_pr_closed')
        for path,raw in candidate_files(record).items():require(github.file(path,pr['head']['sha'])==raw,'original_branch_payload_drift')
        return dict(number=pr['number'],url=pr['html_url'],head=pr['head']['sha'],base=pr['base']['sha'],branch=branch)
    # An ambiguous previous create is inspected above, not silently replayed.
    require(record['status']=='accepted','unknown_pr_creation_requires_reconciliation')
    record['status']='creating_pr';save(record)
    return github.create_pr(branch,'chore(game-monitor): '+record['request_summary'][:100],
        'User-authorized ongoing game-monitor content maintenance. Data-only candidate generated from the current live baseline; executable page code, shared styles, identities, events, business writers and existing collection schedules stay fixed. Existing pr-fast validates the content contract and rendering; publication uses the original locked/CAS publisher with backups and readback. Sources and per-game version evidence are in candidate/request.json.',candidate_files(record))

def refresh_base(github,record,base):
    pr=record['pr'];current=github.request('GET','/pulls/'+str(pr['number']));check_pr(current,record)
    changed=github.request('GET','/compare/'+pr['base']+'...'+base)
    require(not any(row['filename'].startswith(PREFIX) for row in changed['files']),'maintenance_base_conflict')
    files=candidate_files(record)
    tree=github.request('GET','/git/commits/'+base)['tree']['sha']
    record['status']='rebasing';record['rebase_to']=base;save(record)
    tree=github.request('POST','/git/trees',{'base_tree':tree,'tree':[dict(path=p,mode='100644',type='blob',content=b.decode()) for p,b in files.items()]})['sha']
    commit=github.request('POST','/git/commits',dict(message='Refresh current main for game-monitor CI',tree=tree,parents=[pr['head'],base]))['sha']
    record['rebase_commit']=commit;save(record)
    github.request('PATCH','/git/refs/heads/'+record['branch'],dict(sha=commit,force=False))
    require(github.request('GET','/git/ref/heads/'+record['branch'])['object']['sha']==commit,'rebase_readback_failed')
    record['pr'].update(head=commit,base=base);record['status']='pr_open';save(record)

def step(record):
    status=record['status'];folder=STATE/'runs'/record['run_id'];candidate=folder/'candidate'
    if status in TERMINAL:
        if status=='published_file_and_route_readback_verified':
            try:published=strict_json(profile_read('published.json'))
            except (ValueError,OSError):published={}
            expected=dict(run_id=record['run_id'],release=record['release'],index_sha256=record['proof']['after_sha256'],merge_sha=record['merge_commit'])
            if any(published.get(key)!=value for key,value in expected.items()):
                finish(record,publication.verify(Path(record['publication']['stage'])))
        return
    if status in ('blocked','publishing_unknown'):
        if status=='publishing_unknown':
            # Only complete a previous apply if its original journal and all bytes prove success.
            try:result=publication.verify(Path(record['publication']['stage']))
            except (ValueError,OSError):
                try:result=publication.verify_rollback(Path(record['publication']['stage']),record['proof']['before_sha256'])
                except (ValueError,OSError,KeyError):return
                record.update(status='rolled_back_verified',rollback_readback=result);save(record);return
            finish(record,result)
        return
    if status=='finishing':
        finish(record,record['publication_readback']);return
    github=GitHub(TOKEN_FILE)
    if status in ('accepted','creating_pr'):
        record['pr']=open_pr(github,record);record['status']='pr_open';save(record);return
    if status=='rebasing':
        current=github.request('GET','/git/ref/heads/'+record['branch'])['object']['sha']
        require(current==record.get('rebase_commit'),'unknown_rebase_requires_reconciliation')
        record['pr'].update(head=current,base=record['rebase_to']);record['status']='pr_open';save(record);return
    if status=='pr_open':
        pr=github.request('GET','/pulls/'+str(record['pr']['number']));check_pr(pr,record)
        if pr.get('merged'):
            record.update(status='merged',merge_commit=pr['merge_commit_sha']);save(record);return
        base=github.request('GET','/git/ref/heads/main')['object']['sha']
        if base!=record['pr']['base']:refresh_base(github,record,base);return
        if not github.ready(record['pr']):save(record);return
        record['status']='merging';save(record)
        result=github.request('PUT','/pulls/'+str(record['pr']['number'])+'/merge',dict(sha=record['pr']['head'],merge_method='squash'))
        require(result.get('merged') is True,'merge_not_confirmed')
        record.update(status='merged',merge_commit=result['sha']);save(record);return
    if status=='merging':
        pr=github.request('GET','/pulls/'+str(record['pr']['number']));check_pr(pr,record)
        require(pr.get('merged') is True,'unknown_merge_requires_reconciliation')
        record.update(status='merged',merge_commit=pr['merge_commit_sha']);save(record);return
    if status=='merged':
        for path,raw in candidate_files(record).items():require(github.file(path,record['merge_commit'])==raw,'merged_candidate_drift')
        before=(candidate/'before.html').read_bytes();after=(candidate/'index.html').read_bytes()
        require(publication.active().read_bytes()==before,'live_baseline_changed_after_ci')
        record['status']='preparing';save(record)
        record['publication']=publication.prepare(folder/'publication',before,after)
        record['status']='prepared';save(record);return
    if status=='preparing':raise ValueError('interrupted_prepare_preserve_stage')
    if status=='prepared':
        stage=Path(record['publication']['stage'])
        record['status']='publishing';save(record)
        argv=['/opt/python39/bin/python3','-B',str(stage/'release_workspace.py'),'apply','--approved-manifest-sha',record['publication']['manifest_sha256']]
        try:
            child=subprocess.run(argv,capture_output=True,text=True,timeout=85)
            write(folder/'publisher-result.json',dict(exit=child.returncode,stdout=child.stdout,stderr=child.stderr[-2000:]))
            require(child.returncode==0,'publisher_failed_preserve_original_journal')
            finish(record,publication.verify(stage))
        except Exception:
            record['status']='publishing_unknown';save(record);raise
        return
    if status=='publishing':
        record['status']='publishing_unknown';save(record)
        result=publication.verify(Path(record['publication']['stage']));finish(record,result);return
    raise ValueError('unsupported_pipeline_state')

def finish(record,result):
    record['publication_readback']=result;record.update(result);record['status']='finishing'
    record.setdefault('published_at',datetime.now(timezone.utc).isoformat());save(record)
    backup=STATE/'runs'/record['run_id']/'previous-published.json'
    if not backup.exists():
        old_raw=profile_read('published.json',True)
        atomic(backup,old_raw if old_raw else b'{}')
    old=strict_json(backup.read_bytes())
    old.update(published=True,status=result['status'],release=record['release'],index_sha256=record['proof']['after_sha256'],merge_sha=record['merge_commit'],pr=record['pr']['number'],
               maintenance_mode='automatic_data_pr_ci_merge_publish',run_id=record['run_id'],at=record['published_at'],browser_verification='per-run browser evidence separate from file readback')
    write(PROFILE/'published.json',old,True)
    require(strict_json(profile_read('published.json'))==old,'published_metadata_readback_failed')
    record['status']=result['status'];save(record)

def complete_accept(record,raw):
    folder=STATE/'runs'/record['run_id'];candidate=folder/'candidate'
    before=publication.active().read_bytes();after,proof=build(before,strict_json(raw))
    require(proof==record['proof'],'acceptance_baseline_or_request_drift')
    publication.safe(folder);candidate.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name,value in [('before.html',before),('index.html',after),('request.json',raw),('proof.json',json.dumps(proof,ensure_ascii=False,indent=2).encode())]:
        path=candidate/name;publication.safe(path)
        if path.exists():require(path.read_bytes()==value,'partial_candidate_drift')
        else:atomic(path,value)
    record['status']='accepted' if proof['changed'] else 'no_content_change';save(record)
    return record

def accept(raw,record):
    request=strict_json(raw);identity=request.get('run_id')
    require(isinstance(identity,str) and re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}',identity),'run_id_required')
    if record and record['run_id']==identity:
        require(record['request_sha256']==sha(raw),'request_changed_after_acceptance')
        return complete_accept(record,raw) if record['status']=='accepting' else record
    require(not record or record['status'] in TERMINAL,'previous_run_requires_reconciliation')
    folder=STATE/'runs'/identity
    intent=load(STATE/'acceptance-intent.json',{})
    if intent.get('run_id')==identity:
        require(intent['request_sha256']==sha(raw),'original_acceptance_request_drift')
        durable=load(folder/'state.json',{})
        if durable.get('run_id')==identity and durable.get('status')!='accepting':
            require(durable['request_sha256']==sha(raw),'original_run_request_drift');save(durable);return durable
        require(intent['status']=='accepting','run_id_already_used')
        return complete_accept(intent,raw)
    require(not folder.exists(),'run_id_already_used')
    before=publication.active().read_bytes();after,proof=build(before,request)
    record=dict(run_id=identity,request_sha256=sha(raw),request_summary=request['summary'],status='accepting',proof=proof,
                branch='codex/game-monitor-content-'+identity.lower(),accepted_at=datetime.now(timezone.utc).isoformat())
    write(STATE/'acceptance-intent.json',record);save(record)
    return complete_accept(record,raw)

def remember_error(record,error):
    intents=('accepting','creating_pr','merging','rebasing','preparing','publishing','publishing_unknown','finishing')
    transient=isinstance(error,(OSError,TimeoutError,URLError)) and not (isinstance(error,HTTPError) and 400<=error.code<500 and error.code!=429)
    if not transient and record['status'] not in intents:record['status']='blocked'
    record['error']=str(error)[:200] if isinstance(error,ValueError) else type(error).__name__
    record['recovery']='reconcile_original' if record['status'] in intents else 'retry_read' if transient else 'blocked_contract'
    save(record)

def tick():
    import fcntl
    publication.safe(STATE);STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (STATE/'lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        record=load(STATE/'latest.json',{})
        try:
            raw=profile_read('request.json',True)
            if raw:record=accept(raw,record)
        except Exception as error:
            write(PROFILE/'auto-publish-status.json',dict(status='request_rejected',error=str(error)[:200] if isinstance(error,ValueError) else type(error).__name__,previous_run=record.get('run_id')),True)
            raise
        try:
            if record:step(record)
            if record:write(PROFILE/'auto-publish-status.json',record,True)
            export_live()
            return record or {'status':'ready','scope':'game-monitor static data only'}
        except Exception as error:
            # Preserve write-intent states so the next tick reconciles the original operation.
            if record:
                remember_error(record,error)
            else:write(PROFILE/'auto-publish-status.json',dict(status='request_rejected',error=str(error)[:200] if isinstance(error,ValueError) else type(error).__name__),True)
            raise

if __name__=='__main__':print(json.dumps(tick(),ensure_ascii=False,indent=2))
