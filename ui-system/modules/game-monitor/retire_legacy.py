"""One-time retirement of the user-approved old monitor; never publishes UI."""
import ast
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

HOST=Path('/opt/fs-hermes-ops/host.py')
BACKUP=Path('/var/backups/fs-game-monitor-retirement-20261105')
HOST_SHA='60b9ebe936d1807fe60c87ffed2e0d86774498df9d2557c482313ead2e5dc266'
FILES=[Path('/etc/systemd/system/fs-boss-game-monitor.timer'),Path('/etc/systemd/system/fs-boss-game-monitor.service'),
       Path('/opt/fs-hermes-ops/game_monitor/controller.py'),
       Path('/etc/systemd/system/fs-hermes-ops-bridge.service.d/game-monitor-publish.conf')]
DIRECTORIES=[Path('/var/lib/fs-hermes-fc/profile/game-monitor-maintenance'),Path('/var/lib/fs-hermes-ops/game-monitor')]
HOOK="""        try:
            result = subprocess.run(['/opt/python39/bin/python3', '-B', str(HERE/'game_monitor/controller.py')], capture_output=True, text=True, timeout=100)
            if result.returncode: print('game-monitor auto-publication needs attention; inspect its preserved status', flush=True)
        except subprocess.TimeoutExpired:
            print('game-monitor step timed out; reconcile its original journal on the next tick', flush=True)
"""


def strip_hook(raw):
    hook=HOOK.encode()
    if raw.count(hook)!=1:raise ValueError('legacy_bridge_hook_drift')
    after=raw.replace(hook,b'',1)
    ast.parse(after)
    return after


def safe(path):
    if not path.is_absolute() or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('retirement_path_boundary')
    return path


def operation_closed(record, backup_root):
    if record.get('status') in ('published_file_and_route_readback_verified','no_content_change','rolled_back_verified'):
        return True
    # The retired intake parses the old HTML before noticing its already rolled-back operation.
    if record.get('status')!='blocked' or record.get('error')!='literal_marker_ambiguous' or record.get('rollback_readback',{}).get('status')!='rolled_back_verified':
        return False
    publication=record.get('publication',{})
    release=publication.get('release','')
    if not re.fullmatch(r'workspace-native-20261006-[a-f0-9]{12}',release):return False
    folder=safe(backup_root/release)
    try:
        manifest=safe(folder/'approved-manifest.json').read_bytes()
        journal=json.loads(safe(folder/'journal.json').read_bytes())
    except (OSError,ValueError):return False
    digest=hashlib.sha256(manifest).hexdigest()
    return (digest==publication.get('manifest_sha256')==journal.get('approvedManifestSha256')
        and journal.get('status')=='rolled-back-immutable-history-retained' and journal.get('activationAttempted') is False)


def retire():
    import fcntl
    sys.path.insert(0,'/opt/fs-hermes-ops')
    from release_navigation_base import atomic
    for path in [HOST,BACKUP,*FILES,*DIRECTORIES]:safe(path)
    if BACKUP.exists():raise ValueError('original_retirement_exists_reconcile')
    before=HOST.read_bytes()
    if hashlib.sha256(before).hexdigest()!=HOST_SHA:raise ValueError('shared_host_drift')
    after=strip_hook(before)
    public=Path('/var/lib/fs-boss-workspaces/public')
    intelligence=json.loads((public/'intelligence.status.json').read_bytes())
    news=json.loads((public/'seo-news.status.json').read_bytes())
    if intelligence.get('status')!='succeeded' or news.get('schema_version')!=1:
        raise ValueError('replacement_collection_not_verified')
    state=subprocess.check_output(['systemctl','show','fs-boss-game-monitor.service','-p','ActiveState'],universal_newlines=True)
    if state.strip() not in ('ActiveState=inactive','ActiveState=failed'):raise ValueError('old_collection_running_reconcile')
    with Path('/var/lib/fs-hermes-ops/lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if HOST.read_bytes()!=before:raise ValueError('shared_host_concurrent_drift')
        record=json.loads((Path('/var/lib/fs-hermes-ops/game-monitor')/'latest.json').read_bytes())
        if not operation_closed(record,Path('/var/backups/fs-navigation-native-20261006')):
            raise ValueError('original_controller_operation_requires_reconciliation')
        BACKUP.mkdir(mode=0o700)
        receipt=dict(change_id='retire-legacy-game-monitor-20261105',status='started',removed=[],host_before_sha256=HOST_SHA,
            original_controller_state=record['status'],original_operation_closed=True)
        save=lambda:atomic(BACKUP/'receipt.json',json.dumps(receipt,indent=2).encode(),0o600)
        save()
        archive=BACKUP/'retired-runtime.tar.gz'
        cron_store=safe(Path('/var/lib/fs-hermes-fc/profile/cron/jobs.json'))
        paths=[HOST,cron_store,*[p for p in FILES+DIRECTORIES if p.exists()]]
        with tarfile.open(archive,'w:gz',compresslevel=1) as bundle:
            for path in paths:bundle.add(path,arcname=path.relative_to('/').as_posix())
        archive.chmod(0o600)
        with tarfile.open(archive) as bundle:
            for member in bundle:
                if member.isfile():
                    if hashlib.sha256(bundle.extractfile(member).read()).digest()!=hashlib.sha256((Path('/')/member.name).read_bytes()).digest():
                        raise ValueError('retirement_backup_drift')
        digest=hashlib.sha256()
        with archive.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        receipt['archive_sha256']=digest.hexdigest();save()
        code="from cron.jobs import list_jobs,remove_job;import json;rows=list_jobs(include_disabled=True);old=[r for r in rows if r['id']=='6534331b5100'];assert len(old)==1 and '游戏监控台' in old[0]['name'];job=old[0];assert not job.get('fire_claim') and (job.get('latest_execution') or {}).get('status') in (None,'completed','failed','cancelled') and not (job.get('latest_execution') or {}).get('handoff_pending');assert remove_job('6534331b5100');after=list_jobs(include_disabled=True);assert {r['id'] for r in after}=={r['id'] for r in rows}-{'6534331b5100'};print(json.dumps({'removed_job':'6534331b5100'}))"
        result=subprocess.run(['docker','exec','-w','/opt/hermes','fs-hermes-fc','/opt/hermes/.venv/bin/python','-B','-c',code],check=True,capture_output=True,universal_newlines=True)
        receipt['cron']=json.loads(result.stdout);save()
        subprocess.run(['systemctl','disable','--now','fs-boss-game-monitor.timer'],check=True,capture_output=True)
        atomic(HOST,after,0o644)
        if HOST.read_bytes()!=after:raise ValueError('shared_host_readback_failed')
        for path in FILES:
            if path.exists():path.unlink();receipt['removed'].append(str(path));save()
        for path in DIRECTORIES:
            if path.exists():shutil.rmtree(safe(path));receipt['removed'].append(str(path));save()
        subprocess.run(['systemctl','daemon-reload'],check=True)
        receipt.update(status='retired',host_after_sha256=hashlib.sha256(HOST.read_bytes()).hexdigest())
        save()
    print(json.dumps(receipt))


if __name__=='__main__':retire()
