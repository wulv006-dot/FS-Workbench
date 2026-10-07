"""Future approved native execution only; bootstrap frozen root-private artifact first."""
import json,os,sys,hashlib,subprocess,tempfile,importlib,base64
from datetime import datetime,timezone
from verified_loader import install,record,read_verified_sources
from pathlib import Path

def sha(raw):return hashlib.sha256(raw).hexdigest()
def fail(reason):raise ValueError(reason)

def validate_context(scope,snapshots,monitor,gallery,job_rows,execution_rows,queue_rows,source_shas,allowed):
    for key,expected in scope['expected_files'].items():
        if sha(snapshots[key]) not in allowed.get(key,{expected}):fail('scope_file_cas_changed:'+key)
    if source_shas!=scope['expected_sources']:fail('runtime_dependency_changed')
    cp=json.loads(snapshots['config/automation.json']);pp=json.loads(snapshots['config/player-sync.json'])
    if not (cp['system_enabled'] and cp['revision']==28 and cp['schedule_revision']==28 and cp['interval_minutes']==120 and pp['enabled'] and pp['revision']==8):fail('policy_intent_changed')
    # Actual monitor_view contains no Gallery field. Settings.json is a separately bound source.
    if gallery['revision']!=8 or gallery['settings']['enabled'] is not False or gallery['settings']['interval_minutes']!=600:fail('gallery_intent_changed')
    if monitor['publication']['execution_id']!=scope['coin_execution_id']:fail('published_coin_execution_changed')
    if queue_rows or any(j['status'] in ['running','queued'] for j in job_rows):fail('active_or_queued_job_conflict')
    players=[j for j in job_rows if j.get('kind')=='player_sync']
    if not players or max(players,key=lambda j:j['created_at'])['job_id']!=scope['player_job_id']:fail('newer_player_job')
    if any(e.get('status') in ['RUNNING','PARTIAL','UNCERTAIN'] for e in execution_rows):fail('unconfirmed_execution_exists')
    cid=(scope.get('supersession') or {}).get('old_coin_execution_id',scope['coin_execution_id']);audit=json.loads(snapshots['executions/'+cid+'.json']);coin_job=json.loads(snapshots['jobs/'+cid+'.json']);all_ledger=json.loads(snapshots['all-coin-sync/'+cid+'.json'])
    if audit['status']!='CONFIRMED' or audit.get('automatic') is not True or audit['automation_policy_revision']!=28 or audit['all_baseline']['status']!='confirmed':fail('coin_execution_unconfirmed')
    if coin_job['status']!='ready' or coin_job['result']['status']!='confirmed' or coin_job['player_sync']['job_id']!=scope['player_job_id'] or coin_job['player_sync_intent']!={'enabled':True,'revision':8}:fail('coin_job_intent_changed')
    if all_ledger['status']!='confirmed' or len(all_ledger['steps'])!=3 or any(s['status']!='confirmed' for s in all_ledger['steps']):fail('associated_all_writes_unconfirmed')
    if scope.get('supersession'):
        fresh=scope['coin_execution_id'];new=json.loads(snapshots['executions/'+fresh+'.json']);nj=json.loads(snapshots['jobs/'+fresh+'.json']);nl=json.loads(snapshots['all-coin-sync/'+fresh+'.json'])
        if new.get('execution_id')!=fresh or new.get('status')!='CONFIRMED' or new.get('sync_confirmed') is not True or new['created_at']<=audit['created_at'] or new['all_baseline']['status']!='confirmed':fail('superseding_coin_unconfirmed')
        if nj.get('status')!='ready' or (nj.get('result') or {}).get('status') not in ['confirmed','CONFIRMED']:fail('superseding_coin_job_unconfirmed')
        if nl.get('status')!='confirmed' or len(nl.get('steps',[]))!=3 or any(s.get('status')!='confirmed' for s in nl['steps']):fail('superseding_all_unconfirmed')
    latest=max((j for j in job_rows if j.get('kind')=='auto_cycle'),key=lambda j:j['created_at'])
    if latest['status']!='ready' or latest.get('error') or latest.get('error_detail'):fail('latest_cycle_needs_separate_audit')

def process_identity(pid):
    return Path('/proc/'+str(pid)+'/stat').read_text('utf-8').rsplit(')',1)[1].split()[19]

def validate_writers(scope,storage,adoption_validator):
    # Approved inline launch supplies its already reviewed receipt validator.
    # Private binding SHA approval authenticates receipts; process continuity and
    # worker live heartbeat remain checked here before any metadata publication.
    adoption_validator(scope)
    evidence=scope['writer_protocol_evidence']
    for role in ['api','worker']:
        bound=evidence[role]
        if bound['protocol']!='existing-tick-inode-v4' or process_identity(bound['pid'])!=str(bound['start_ticks']):fail('active_writer_protocol_not_proven:'+role)
        command=Path('/proc/'+str(bound['pid'])+'/cmdline').read_bytes().split(b'\x00')
        if ('/opt/fc27-cloud-browser/fc27_cloud_'+role+'.py').encode() not in command:fail('active_writer_command_changed:'+role)
    if evidence['timer']['protocol']!='existing-tick-inode-v4':fail('timer_protocol_not_proven')
    heartbeat=json.loads(storage.fs.read_path(storage.root+'/state/worker-heartbeat.json',{'uid':0,'gid':11028,'mode':'0o640'}))
    age=(datetime.now(timezone.utc)-datetime.fromisoformat(heartbeat['at'])).total_seconds()
    if not 0<=age<=15 or heartbeat.get('queue_protocol')!='existing-tick-inode-v4' or heartbeat.get('pid')!=evidence['worker']['pid']:fail('live_worker_protocol_not_proven')

# Executed as inline bytes in the fixed image with -I; all input SHA checks occur
# before executing even the candidate loader. The image owns stdlib/site packages.
PROBE_BOOTSTRAP="""import os,sys,json,hashlib,base64
raw=sys.stdin.buffer.read(32000001)
if len(raw)>32000000 or hashlib.sha256(raw).hexdigest()!=sys.argv[1]:raise ValueError('probe_input_changed')
bundle=json.loads(raw)
if set(bundle['candidate'])!={'probe','verified_loader'}:raise ValueError('probe_candidate_closure_invalid')
sources={k:base64.b64decode(v,validate=True) for k,v in bundle['candidate'].items()}
for k,v in sources.items():
 if hashlib.sha256(v).hexdigest()!=bundle['candidate_sha256'][k]:raise ValueError('probe_candidate_hash_changed')
loader=type(sys)('verified_loader');loader.__file__='verified-memory:verified_loader.py'
exec(compile(sources['verified_loader'],loader.__file__,'exec'),loader.__dict__);sys.modules['verified_loader']=loader
loader.install({'probe':sources['probe']},{'probe':bundle['candidate_sha256']['probe']},{'probe':'verified candidate probe'}, {'probe'})
import probe
probe.main(bundle['scope'])
"""

def run(scope,manifest_sha,binding_sha,candidate,apply=False,adoption_validator=None):
    if not callable(adoption_validator):fail('approved_writer_receipt_validator_required')
    if sys.version!=scope['host_python']['version'] or sha(Path(sys.executable).resolve().read_bytes())!=scope['host_python']['executable_sha256']:fail('host_interpreter_changed')
    if scope['proof_provenance'].get('loader')!='sealed-memory-v1':fail('sealed_proof_binding_required')
    sys.dont_write_bytecode=True
    from storage import Storage
    from reconcile import Recovery
    storage=Storage(scope)
    try:
        storage.fs.lock('automation-tick.lock');storage.fs.lock('price-writer.lock')
        sources,expected,origins=read_verified_sources(scope)
        for name in sources:
            if sha(candidate['app/'+name+'.py'])!=expected[name]:fail('approved_source_artifact_mismatch')
        names={Path(path).stem for path in scope['expected_sources']}
        if names!={'fc27_cloud_api','fc27_cloud_worker','player_sync_job','automation_tick','coin_all_sync_job','automation_policy','player_sync_policy','server_quote_job','activity_log_store','fc27_quote_engine','snapshot_layer','storefront_monitor'}:fail('runtime_closure_allowlist_changed')
        install(sources,expected,origins,names)
        import fc27_cloud_api as api
        validate_writers(scope,storage,adoption_validator)
        def context(allowed):
            storage.fs.check();validate_writers(scope,storage,adoption_validator)
            for name in scope['lock_metadata']:
                if name not in storage.fs.locks:storage.fs.lock_free(name)
            if scope.get('shell_source'):
                shell=scope['shell_source']
                if sha(storage.fs.read_path(shell['path'],shell['metadata']))!=shell['sha256']:fail('runtime_shell_source_changed')
            snapshots={key:storage.read_live(key) for key in scope['expected_files']}
            source_shas={path:sha(storage.source_bytes(path)) for path in scope['expected_sources']}
            validate_context(scope,snapshots,api.monitor_view(),json.loads(snapshots['/var/lib/fc27-gallery/settings.json']),storage.json_directory('jobs'),storage.json_directory('executions'),storage.json_directory('queue'),source_shas,allowed)
            for path,wanted in scope['expected_sources'].items():
                name=Path(path).stem
                if name in sys.modules and record(sys.modules[name])!={'path':path,'sha256':wanted}:fail('loaded_host_module_origin_changed')
        def probe(ledger,raw_ledger):
            with tempfile.TemporaryDirectory(prefix='fc27-reconcile-v4-input-') as tmp:
                source=Path(tmp)/'ledger.json';source.write_bytes(raw_ledger);os.chown(source,0,11028);os.chmod(source,0o640)
                bundle={'scope':scope,'candidate':{n:base64.b64encode(candidate[n+'.py']).decode('ascii') for n in ['probe','verified_loader']},'candidate_sha256':{n:sha(candidate[n+'.py']) for n in ['probe','verified_loader']}}
                raw=json.dumps(bundle,separators=(',',':')).encode()
                if len(raw)>32000000:fail('probe_input_changed')
                cmd=['timeout','70s','docker','run','--rm','-i','--network','fc27-cloud-net','--read-only','--tmpfs','/tmp:rw,noexec,nosuid,size=64m','--cap-drop','ALL','--security-opt','no-new-privileges','--group-add','11028']
                for src,dst in [('/etc/fc27-cloud/fc27.env','/run/secrets/fc27.env'),('/var/lib/fc27-cloud','/var/lib/fc27-cloud'),('/opt/fc27-cloud-browser','/opt/fc27-cloud-browser'),(source,'/run/reconcile-original-ledger.json')]:cmd+=['--mount','type=bind,src='+str(src)+',dst='+dst+',readonly']
                cmd+=['--entrypoint','python3',scope['container_image_id'],'-I','-B','-c',PROBE_BOOTSTRAP,sha(raw)]
                result=subprocess.run(cmd,input=raw,capture_output=True,timeout=75)
                if result.returncode:fail('fresh_readback_unavailable')
                return json.loads(result.stdout)
        if scope.get('supersession'):
            from supersede import Supersession
            operation=Supersession
        else:operation=Recovery
        result=operation(storage,scope,manifest_sha,context,probe).run(apply=apply)
        result['runtime_binding_sha256']=binding_sha;print(json.dumps(result))
        if result['status']=='metadata_may_be_committed_needs_readback':raise SystemExit(3)
    finally:storage.close()

if __name__=='__main__':fail('use_approved_inline_isolated_launcher')
