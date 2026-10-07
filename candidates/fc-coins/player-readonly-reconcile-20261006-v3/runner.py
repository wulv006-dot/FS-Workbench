"""Future approved native execution only; bootstrap frozen root-private artifact first."""
import argparse,json,os,stat,sys,hashlib,subprocess,tempfile,importlib
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
    cid=scope['coin_execution_id'];audit=json.loads(snapshots['executions/'+cid+'.json']);coin_job=json.loads(snapshots['jobs/'+cid+'.json']);all_ledger=json.loads(snapshots['all-coin-sync/'+cid+'.json'])
    if audit['status']!='CONFIRMED' or audit.get('automatic') is not True or audit['automation_policy_revision']!=28 or audit['all_baseline']['status']!='confirmed':fail('coin_execution_unconfirmed')
    if coin_job['status']!='ready' or coin_job['result']['status']!='confirmed' or coin_job['player_sync']['job_id']!=scope['player_job_id'] or coin_job['player_sync_intent']!={'enabled':True,'revision':8}:fail('coin_job_intent_changed')
    if all_ledger['status']!='confirmed' or len(all_ledger['steps'])!=3 or any(s['status']!='confirmed' for s in all_ledger['steps']):fail('associated_all_writes_unconfirmed')
    latest=max((j for j in job_rows if j.get('kind')=='auto_cycle'),key=lambda j:j['created_at'])
    if latest['status']!='ready' or latest.get('error') or latest.get('error_detail'):fail('latest_cycle_needs_separate_audit')

def bootstrap(folder,manifest_sha):
    if os.name!='posix' or os.geteuid()!=0:fail('native_existing_root_access_required')
    if str(folder)!='/opt/fc27-player-reconcile-20261006-v2':fail('artifact_path_outside_approved_scope')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);fds=[fd]
    try:
        root_stat=os.fstat(fd)
        if root_stat.st_uid!=0 or stat.S_IMODE(root_stat.st_mode)&0o022:fail('root_parent_owner_mode_untrusted')
        for segment in ['opt','fc27-player-reconcile-20261006-v2']:
            nextfd=os.open(segment,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);fds.append(nextfd);st=os.fstat(nextfd)
            if st.st_uid!=0 or stat.S_IMODE(st.st_mode)&0o022:fail('artifact_parent_owner_mode_untrusted')
            if segment.endswith('-v2') and (st.st_gid!=0 or stat.S_IMODE(st.st_mode)!=0o700):fail('artifact_not_root_private')
            if (st.st_dev,st.st_ino)!=(os.stat(segment,dir_fd=fd,follow_symlinks=False).st_dev,os.stat(segment,dir_fd=fd,follow_symlinks=False).st_ino):fail('artifact_parent_inode_changed')
            fd=nextfd
        def read_one(name):
            if '/' in name or name in ['.','..']:fail('candidate_file_path_invalid')
            filefd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
            try:
                st=os.fstat(filefd)
                if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_uid!=0 or st.st_gid!=11028 or stat.S_IMODE(st.st_mode)!=0o640:fail('candidate_file_owner_mode_untrusted')
                with os.fdopen(filefd,'rb',closefd=False) as stream:raw=stream.read(32000000)
                current=os.stat(name,dir_fd=fd,follow_symlinks=False)
                if (current.st_dev,current.st_ino)!=(st.st_dev,st.st_ino):fail('candidate_file_inode_changed')
                return raw
            finally:os.close(filefd)
        raw=read_one('CANDIDATE-MANIFEST.json')
        if sha(raw)!=manifest_sha:fail('candidate_manifest_changed')
        manifest=json.loads(raw)
        for name,expected in manifest['files'].items():
            if sha(read_one(name))!=expected:fail('candidate_input_changed')
        return json.loads(read_one('scope.json'))
    finally:
        for descriptor in reversed(fds):os.close(descriptor)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest-sha',required=True);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    folder=Path(__file__).absolute().parent;scope=bootstrap(folder,args.manifest_sha)
    if sys.version!=scope['host_python']['version'] or sha(Path(sys.executable).resolve().read_bytes())!=scope['host_python']['executable_sha256']:fail('host_interpreter_changed')
    sys.dont_write_bytecode=True;sys.path.insert(0,str(folder));from storage import Storage;from reconcile import Recovery
    storage=Storage(scope)
    try:
        storage.fs.lock('automation-tick.lock');storage.fs.lock('price-writer.lock')
        for path,expected in scope['expected_sources'].items():
            if sha(storage.source_bytes(path))!=expected:fail('runtime_source_changed_before_import')
        sys.path.insert(0,'/opt/fc27-cloud-browser');import fc27_cloud_api as api
        def context(allowed):
            storage.fs.check()
            for name in scope['lock_metadata']:
                if name not in storage.fs.locks:storage.fs.lock_free(name)
            snapshots={key:storage.read_live(key) for key in scope['expected_files']};source_shas={path:sha(storage.source_bytes(path)) for path in scope['expected_sources']}
            validate_context(scope,snapshots,api.monitor_view(),json.loads(snapshots['/var/lib/fc27-gallery/settings.json']),storage.json_directory('jobs'),storage.json_directory('executions'),storage.json_directory('queue'),source_shas,allowed)
            for path,expected in scope['expected_sources'].items():
                module_name=Path(path).stem
                if module_name in sys.modules:
                    actual=Path(sys.modules[module_name].__file__).resolve()
                    if str(actual)!=path or sha(actual.read_bytes())!=expected:fail('loaded_host_module_origin_changed')
        def probe(ledger,raw_ledger):
            with tempfile.TemporaryDirectory(prefix='fc27-reconcile-v2-input-') as tmp:
                source=Path(tmp)/'ledger.json';source.write_bytes(raw_ledger);os.chown(source,0,11028);os.chmod(source,0o640)
                cmd=['timeout','70s','docker','run','--rm','--network','fc27-cloud-net','--read-only','--tmpfs','/tmp:rw,noexec,nosuid,size=64m','--cap-drop','ALL','--security-opt','no-new-privileges','--group-add','11028']
                for src,dst in [('/etc/fc27-cloud/fc27.env','/run/secrets/fc27.env'),('/var/lib/fc27-cloud','/var/lib/fc27-cloud'),('/opt/fc27-cloud-browser','/opt/fc27-cloud-browser'),(folder/'probe.py','/opt/probe.py'),(folder/'scope.json','/run/reconcile-scope.json'),(source,'/run/reconcile-original-ledger.json')]:cmd+=['--mount','type=bind,src='+str(src)+',dst='+dst+',readonly']
                cmd+=['--entrypoint','python3',scope['container_image_id'],'-B','/opt/probe.py'];result=subprocess.run(cmd,capture_output=True,timeout=75)
                if result.returncode:fail('fresh_readback_unavailable')
                return json.loads(result.stdout)
        result=Recovery(storage,scope,args.manifest_sha,context,probe).run(apply=args.apply);print(json.dumps(result))
        if result['status']=='metadata_may_be_committed_needs_readback':raise SystemExit(3)
    finally:storage.close()

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'stopped_without_business_replay','reason':str(exc)[:120] if isinstance(exc,ValueError) else type(exc).__name__,'business_posts':0}));raise SystemExit(2)
