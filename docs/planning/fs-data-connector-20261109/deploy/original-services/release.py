"""Exact connector delta adapter for the existing frozen FS publisher and readiness."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys

import runtime_release as release

HERE=Path(__file__).resolve().parent
SCOPE='fs-connector-original-readonly-20261109'
TARGETS={'http/conversation_http.py':'/opt/fs-exact-range-20261001/conversation_http.py',
         'http/conversation_readonly.py':'/opt/fs-exact-range-20261001/conversation_readonly.py'}
TARGETS.update({'runtime/'+name:'/opt/fs-hermes-fc/'+name for name in (
    'tracking_controller.py','tracking_readonly.py','tracking_tool.py','customer_tracking.py',
    'pool_reports.py','customer_reports.py','research.py')})
NEW={'http/conversation_readonly.py','runtime/tracking_readonly.py'}


def digest(raw):return hashlib.sha256(raw).hexdigest()


def frozen():
    release.SCOPE=SCOPE
    return release.frozen(TARGETS,new=NEW)


def proof():
    value=json.loads((HERE/'source-proof.json').read_bytes())
    if set(value['files'])!=set(TARGETS):raise ValueError('exact_delta_sources_required')
    for name,row in value['files'].items():
        if row['target']!=TARGETS[name] or (row['before_sha256'] is None)!=(name in NEW):
            raise ValueError('exact_delta_target_required')
        raw=(HERE/'candidate'/name).read_bytes()
        if digest(raw)!=row['after_sha256']:raise ValueError('reviewed_delta_source_changed')
        compile(raw,row['target'],'exec')
        if name not in NEW and digest((HERE/'before'/name).read_bytes())!=row['before_sha256']:
            raise ValueError('observed_before_source_changed')
    return value


def idle(base,root):
    release.quiescent(base,root)
    path=base.rooted(root,'/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db')
    base.no_target_link(path)
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pool_reports'").fetchone():
            if db.execute("SELECT count(*) FROM pool_reports WHERE state IN ('creating','dispatch_unknown','queued','pending','running')").fetchone()[0]:
                raise ValueError('active_or_unknown_customer_pool_report')


def activity_summary(base,root):
    result={}
    for relative,table,states in (
        ('tasks.sqlite3','requests',('PREPARING','DISPATCH_UNKNOWN','RUNNING','CANCEL_REQUESTED','NEEDS_RECONCILE')),
        ('tasks.sqlite3','tasks',('QUEUED','DISPATCH_UNKNOWN','RUNNING','VALIDATING','NEEDS_RECONCILE')),
        ('tasks.sqlite3','learning_events',('running','unknown')),
        ('conversations/conversations.db','turns',('preparing','dispatch_unknown','queued','running','stopping')),
        ('pricing-reviews/conversations.db','turns',('preparing','dispatch_unknown','queued','running','stopping')),
        ('customer-tracking/tracking.db','scan_jobs',('pending',)),
        ('customer-tracking/tracking.db','milestones',('claimed','creating','dispatch_unknown','queued','running')),
        ('customer-tracking/tracking.db','pool_reports',('creating','dispatch_unknown','queued','pending','running'))):
        path=base.rooted(root,'/var/lib/fs-hermes-fc/fs/'+relative);key=relative+':'+table
        if not path.exists():result[key]={'status':'store_missing'};continue
        try:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
                    result[key]={'status':'table_missing'};continue
                result[key]={'status':'available','states':{state:db.execute('SELECT count(*) FROM '+table+' WHERE state=?',(state,)).fetchone()[0] for state in states}}
        except sqlite3.Error:result[key]={'status':'read_error'}
    return result


def observe():
    value=proof();base=frozen();rows=[]
    required=release.software_protected_paths(base,set(TARGETS.values()))
    for name in sorted(set(TARGETS.values())|required):
        p=Path(name);base.no_target_link(p)
        if not p.exists():
            if name not in {TARGETS[n] for n in NEW}:raise ValueError('existing_source_missing:'+name)
            rows.append({'path':name,'sha256':None});continue
        info=p.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('source_file_boundary')
        rows.append({'path':name,'sha256':digest(p.read_bytes()),'owner':str(info.st_uid)+':'+str(info.st_gid),
                     'mode':oct(stat.S_IMODE(info.st_mode))})
    current={r['path']:r for r in rows}
    for name,row in value['files'].items():
        if current[row['target']]['sha256']!=row['before_sha256']:raise ValueError('fresh_source_CAS_drift:'+name)
    worker=release.worker_observation()
    if worker['state']!='active':raise ValueError('worker_not_active')
    try:base.hermes_quiescent(Path('/'));idle(base,Path('/'))
    except ValueError as error:
        print(json.dumps({'quiescence_error':str(error),'activity':activity_summary(base,Path('/'))}))
        raise
    return {'observed_at':datetime.now(timezone.utc).isoformat(),'files':rows,'worker':worker,
            'source_proof_sha256':digest((HERE/'source-proof.json').read_bytes()),'production_writes':0}


def prepare(ready):
    value=proof()
    if not re.fullmatch('[a-f0-9]{40}',value.get('source_commit','')):raise ValueError('full_reviewed_source_commit_required')
    observed=observe();rows={r['path']:r for r in observed['files']}
    files=[{'candidate':name,'target':row['target'],'sha256':row['after_sha256'],
            'beforeSha256':row['before_sha256'],'owner':'0:0','mode':'0o644'} for name,row in value['files'].items()]
    helpers={name:digest((HERE/name).read_bytes()) for name in (
        'release.py','runtime_release.py','runtime_prepare.py','release_navigation_base.py','release_readiness.py')}
    manifest={'schemaVersion':1,'scope':SCOPE,'sourceCommit':value['source_commit'],
        'releaseReady':ready,'imageId':release.FROZEN_IMAGE_MARKER,
        'workerImageId':observed['worker']['image'],'workerImageSource':'container',
        'businessWrites':False,'timersChanged':False,'files':files,
        'runtimeRequired':{u:{'ActiveState':'active'} for u in ('fs-business-range.service','fs-hermes-fc.service')},
        'unchangedRequired':[row for path,row in sorted(rows.items()) if path not in TARGETS.values()],
        'baselineObservedAt':observed['observed_at'],'sourceProofSha256':observed['source_proof_sha256'],
        'deploymentHelpers':helpers}
    raw=json.dumps(manifest,ensure_ascii=False,indent=2).encode()
    (HERE/'approved-manifest.json').write_bytes(raw)
    (HERE/'observation.json').write_text(json.dumps(observed,indent=2),encoding='utf-8')
    return {'manifest_sha256':digest(raw),'files':len(files),'production_writes':0,'release_ready':ready}


def load_base():
    value=proof();approved=json.loads((HERE/'approved-manifest.json').read_bytes());base=frozen()
    if approved.get('scope')!=SCOPE or approved.get('sourceProofSha256')!=digest((HERE/'source-proof.json').read_bytes()):
        raise ValueError('exact_source_proof_required')
    for name,sha in approved['deploymentHelpers'].items():
        if digest((HERE/name).read_bytes())!=sha:raise ValueError('deployment_helper_changed')
    original_validate=base.validate;original_idle=base.hermes_quiescent
    original_restart=base.restart_for;original_inspect=base.inspect
    def validate(manifest,stage):
        if manifest!=approved or {r['candidate']:r['target'] for r in manifest['files']}!=TARGETS:
            raise ValueError('exact_approved_delta_manifest_required')
        for row in manifest['files']:
            source=value['files'][row['candidate']]
            if row['beforeSha256']!=source['before_sha256'] or row['sha256']!=source['after_sha256'] or row['owner']!='0:0' or row['mode']!='0o644':
                raise ValueError('exact_reviewed_delta_required')
        if {r['path'] for r in manifest['unchangedRequired']}!=release.software_protected_paths(base,set(TARGETS.values())):
            raise ValueError('original_protected_set_required')
        return original_validate(manifest,stage)
    def quiescent(root):original_idle(root);idle(base,root)
    def inspect(manifest,stage,root=Path('/')):
        result=original_inspect(manifest,stage,root)
        if root==Path('/'):
            release.running_worker(manifest)
            program="import sys;from pathlib import Path;sys.path[:0]=sys.argv[1:];import conversation_http,conversation_readonly,tracking_controller,tracking_readonly,tracking_tool,customer_tracking,pool_reports;assert all(Path(m.__file__).resolve()==Path(sys.argv[1])/n for m,n in ((conversation_http,'conversation_http.py'),(conversation_readonly,'conversation_readonly.py')));assert all(Path(m.__file__).resolve()==Path(sys.argv[2])/n for m,n in ((tracking_controller,'tracking_controller.py'),(tracking_readonly,'tracking_readonly.py'),(tracking_tool,'tracking_tool.py'),(customer_tracking,'customer_tracking.py'),(pool_reports,'pool_reports.py')));assert callable(tracking_readonly.stored_get);assert callable(tracking_tool.customer_snapshot);assert callable(conversation_readonly.files_list);assert callable(conversation_readonly.material_metadata)"
            check=subprocess.run([sys.executable,'-I','-B','-c',program,str(HERE/'candidate/http'),str(HERE/'candidate/runtime'),'/opt/fs-hermes-fc','/opt/fs-exact-range-20261001'],capture_output=True,timeout=20)
            if check.returncode:raise ValueError('composed_original_delta_import_failed')
        return result
    def restart(manifest,admission_fence=None):
        if admission_fence is None:raise ValueError('original_admission_fence_required')
        admission_fence.stop_then_unlock_database()
        # The running worker registers research.tool_schemas at adapter startup.
        result=None
        for scope in (base.HERMES_WORKER_SCOPE,base.DEEP_SCOPE):
            result=release.software_restart(base,original_restart,dict(manifest,scope=scope),admission_fence)
        release.running_worker(manifest)
        base.guards(manifest,admission_fence.root)
        return result
    base.validate=validate;base.hermes_quiescent=quiescent;base.inspect=inspect;base.restart_for=restart
    return base


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1] in ('observe','prepare'):
        result=observe() if sys.argv[1]=='observe' else prepare('--release-ready' in sys.argv[2:])
        print(json.dumps(result,indent=2))
    else:load_base().main()
