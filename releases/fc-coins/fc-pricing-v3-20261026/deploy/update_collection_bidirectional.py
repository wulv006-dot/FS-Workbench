"""Pinned bidirectional collection-role update; reuse the original atomic swap and rollback. Preview default; no source or business task dispatch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
import re
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

if not __debug__:
    raise ValueError('validation_checks_required')

OLD = {'node':'55eeff178d37e4747c1fe5b4f3d49b9a258b4d5cf7eeb75a6cbf6493cba5b14d',
       'control':'53e1e8fa7719d57e35a7dc33a200948827ef06e8479e70922379479834f913ec'}
NEW = {'node':'2360f21883ae0a823810b44255ca7e31808c7d942bdaff8c22c0ff9f09f9dabd',
       'control':'1236c157e31415ac60b404e980c03adf631bbdc5bb8fa1e1e4236502c2f0928a'}
WORKER = '49ac963bb2744c3f54ed0383d6570781ef709c4eb9374a4e850e3cab77dd5085'
OLD_WORKER = '0665b89d7d6e074f1a06c10672c1f2f4c5d55ea86bea6b214bb1e434a0fc5a7e'
OLD_NAMES = {'node':'node-3f4aa53f.zip','control':'control-6d395242.zip'}
STAGE = Path('/var/tmp/fs-fc-bidirectional-20261107')
CHANGED = {role:{'fc_collection/' + name for name in ('contracts.py','public_sources.py','adapters.py','worker.py')} | {'manifest.json'}
           | ({'fc_collection/client.py'} if role == 'control' else set()) for role in ('node','control')}


def read_bundle(path, digest, role):
    path=Path(path)
    assert role in OLD and not path.is_symlink() and path.stat().st_size<=8388608
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    node={'fc_collection/'+n for n in ('__init__.py','contracts.py','worker.py','adapters.py','protocol.py','public_sources.py','server.py')}|{'entry.py','manifest.json'}
    control={'fc_collection/'+n for n in ('__init__.py','contracts.py','coordinator.py','protocol.py','ssh_client.py','public_sources.py','pilot.py','client.py','adapters.py','worker.py','failover.py')}|{'entry.py','manifest.json'}
    allowed=node if role=='node' else control
    with zipfile.ZipFile(path) as archive:
        members=archive.infolist()
        assert len(members)==len(allowed) and {m.filename for m in members}==allowed
        assert sum(m.file_size for m in members)<=4194304
        assert all(m.file_size<=1048576 and not stat.S_ISLNK(m.external_attr>>16) for m in members)
        files={m.filename:archive.read(m) for m in members}
    manifest=json.loads(files['manifest.json'])
    assert manifest['schema_version']==1 and manifest['role']==('limited_fc_collector' if role=='node' else 'fc_collection_controller')
    assert manifest['credentials']==[] and manifest['business_runtime'] is False and manifest['production_consume'] is False
    assert manifest['sources']==['ArabUT'] and set(manifest['sha256'])==allowed-{'manifest.json'}
    assert all(hashlib.sha256(files[k]).hexdigest()==v for k,v in manifest['sha256'].items())
    return files


def atomic(path, body, mode):
    fd, name = tempfile.mkstemp(prefix='.bidirectional-', dir=str(path.parent))
    with os.fdopen(fd, 'wb') as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(name, mode)
    os.replace(name, path)

def update(bundle, digest, worker_digest, apply):
    assert os.geteuid() == 0
    host = socket.gethostname()
    role = {'FSHTUS01': 'node', 'play187': 'control'}[host]
    assert digest == NEW[role] and worker_digest == WORKER
    root = Path('/opt/fs-fc-collector' if role == 'node' else '/opt/fs-fc-control')
    previous = read_bundle(STAGE / OLD_NAMES[role], OLD[role], role)
    files = read_bundle(bundle, digest, role)
    assert {name for name in files if files[name] != previous[name]} == CHANGED[role]
    receipt = root/'bidirectional-update-20261107.json'
    reference = files if receipt.exists() else previous
    expected = root / 'code'
    assert not root.is_symlink() and root.stat().st_uid == 0
    assert not expected.is_symlink() and expected.is_dir()
    actual = set()
    for path in expected.rglob('*'):
        assert not path.is_symlink() and path.stat().st_uid == 0
        if path.is_file():
            actual.add(path.relative_to(expected).as_posix())
            assert path.read_bytes() == reference[path.relative_to(expected).as_posix()]
    assert actual == set(reference)
    if receipt.exists():
        saved=json.loads(receipt.read_text())
        assert saved['phase']=='updated' and saved['new_bundle_sha256']==digest and saved['worker_digest']==WORKER
        if role=='control':
            access=Path('/var/lib/fc27-cloud/collection-access/access.json')
            assert not access.is_symlink() and access.stat().st_uid==0 and access.stat().st_nlink==1
            assert stat.S_IMODE(access.stat().st_mode)==0o600 and json.loads(access.read_text())['worker_digest']==WORKER
        return dict(saved, phase='already_updated')
    backup = root / 'code-before-bidirectional-20261107'
    assert not backup.exists() and not backup.is_symlink()
    failed = root / ('code-bidirectional-failed-' + uuid.uuid4().hex)
    assert not failed.exists() and not failed.is_symlink()
    old_config = None
    access = Path('/var/lib/fc27-cloud/collection-access/access.json')
    if role == 'control':
        assert not access.is_symlink() and access.stat().st_uid == 0 and access.stat().st_nlink == 1
        assert stat.S_IMODE(access.stat().st_mode) == 0o600
        old_config = access.read_bytes()
        config = json.loads(old_config)
        assert config['worker_digest'] == OLD_WORKER
        config['worker_digest'] = worker_digest
    else:
        assert hashlib.sha256(files['manifest.json']).hexdigest() == worker_digest
        assert not list(Path('/var/lib/fs-fc-collector/spool').iterdir())
    result = dict(host=host, role=role, old_bundle_sha256=OLD[role], new_bundle_sha256=digest,
                  worker_digest=worker_digest, phase='preview')
    if not apply:
        return result
    candidate = Path(tempfile.mkdtemp(prefix='.code-bidirectional-', dir=str(root)))
    candidate.chmod(0o755)
    for relative, body in files.items():
        target = candidate / relative
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        target.parent.chmod(0o755)
        target.write_bytes(body)
        target.chmod(0o444)
    switched = False
    try:
        if role == 'node':
            subprocess.run(['systemctl', 'stop', 'fs-fc-collector.service'], check=True)
        expected.rename(backup)
        candidate.rename(expected)
        switched = True
        if role == 'control':
            atomic(access, (json.dumps(config, sort_keys=True) + '\n').encode(), 0o600)
        else:
            subprocess.run(['systemctl', 'start', 'fs-fc-collector.service'], check=True)
            health = None
            for _ in range(50):
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                        connection.settimeout(2)
                        connection.connect('/run/fs-fc-collector/worker.sock')
                        connection.sendall(b'{"method":"health"}\n')
                        with connection.makefile('rb') as response:
                            health = json.loads(response.readline(65537))
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    time.sleep(.1)
            assert health and health['worker_digest'] == worker_digest and health['uid'] == 999
        result.update(phase='updated', backup=str(backup), updated_at=datetime.now(timezone.utc).isoformat())
        atomic(receipt, (json.dumps(result, sort_keys=True) + '\n').encode(), 0o600)
        return result
    except BaseException:
        if switched:
            if role == 'node':
                subprocess.run(['systemctl', 'stop', 'fs-fc-collector.service'], check=True)
            expected.rename(failed)
            backup.rename(expected)
        elif backup.exists() and not expected.exists():
            backup.rename(expected)
        if old_config is not None:
            atomic(access, old_config, 0o600)
        if role == 'node':
            subprocess.run(['systemctl', 'start', 'fs-fc-collector.service'], check=True)
        raise

LOOTBAR_SCOPE='fc-lootbar-183-fallback-20261111'
LOOTBAR_ROLE_FILES={
    'node':{'fc_collection/'+n for n in ('__init__.py','contracts.py','worker.py','adapters.py','protocol.py','public_sources.py','server.py','lootbar.py')}|{'entry.py','manifest.json'},
    'control':{'fc_collection/'+n for n in ('__init__.py','contracts.py','coordinator.py','protocol.py','ssh_client.py','public_sources.py','pilot.py','client.py','adapters.py','worker.py','failover.py','lootbar.py')}|{'entry.py','manifest.json'}}
LOOTBAR_BEFORE_MANIFEST={'node':WORKER,'control':'56162eaf67b371a178a3c15d95631ac1e76e010de65e45fca293b3c14f8ff87e'}
LOOTBAR_ROOTS={'node':Path('/opt/fs-fc-collector'),'control':Path('/opt/fs-fc-control'),'renderer':Path('/opt/d4follow/_qd_render')}
LOOTBAR_RENDERER_FILES={'qd_render_svc.py','fc27_lootbar.py','lootbar_background.js'}
LOOTBAR_RENDERER_PROTECTED=('/opt/d4follow/core_qd.py','/opt/d4follow/app.py','/opt/d4follow/config.json','/opt/d4follow/_qd_render/start.sh','/etc/systemd/system/d4follow-collect.timer')
LOOTBAR_RENDERER_IMAGE='sha256:c00943affd877dfcb937d752afbafd7c195e7b94e03d0321dc16dfbf2ae3be93'
LOOTBAR_RENDERER_RESOURCES=dict(Memory=3221225472,NanoCpus=0,ShmSize=1073741824,RestartPolicy={'Name':'always','MaximumRetryCount':0})
LOOTBAR_RENDERER_BEFORE='ef0679ad35a4d42d791db2cc44cd27861b52b3bde44127c9707bcb17d97670a7'
LOOTBAR_PARSER_SHA='e0e1946f607ae37df8547788d3252d05e02f5251ffae9c744ed9e941712e298e'
LOOTBAR_ACCESS=Path('/var/lib/fc27-cloud/collection-access/access.json')
LOOTBAR_SPOOL=Path('/var/lib/fs-fc-collector/spool')
LOOTBAR_ROLE_PROTECTED={'node':('/etc/systemd/system/fs-fc-collector.service',),
    'control':('/var/lib/fc27-cloud/collection-access/routing.json',)}


def _lootbar_sha(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('lootbar_target_link')
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _lootbar_root_owned(path):
    return os.name!='posix' or (Path(path).stat().st_uid,Path(path).stat().st_gid)==(0,0)


def _lootbar_access_read():
    p=LOOTBAR_ACCESS
    if p.is_symlink() or not p.is_file():raise ValueError('lootbar_access_file_invalid')
    info=p.stat()
    if os.name=='posix' and (info.st_uid!=0 or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600):raise ValueError('lootbar_access_metadata_drift')
    return p.read_bytes()


def read_lootbar_bundle(path,digest,role):
    if role not in LOOTBAR_ROLE_FILES and role!='renderer':raise ValueError('lootbar_role_invalid')
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>8388608 or _lootbar_sha(path)!=digest:
        raise ValueError('lootbar_bundle_hash_invalid')
    allowed=LOOTBAR_RENDERER_FILES if role=='renderer' else LOOTBAR_ROLE_FILES[role]
    with zipfile.ZipFile(path) as z:
        info=z.infolist()
        if len(info)!=len(allowed) or {x.filename for x in info}!=allowed or any(stat.S_ISLNK(x.external_attr>>16) or x.file_size>1048576 for x in info) or sum(x.file_size for x in info)>4194304:
            raise ValueError('lootbar_bundle_files_invalid')
        files={x.filename:z.read(x) for x in info}
    if role=='renderer':
        if hashlib.sha256(files['lootbar_background.js']).hexdigest()!=LOOTBAR_PARSER_SHA:raise ValueError('lootbar_parser_pin_changed')
    else:
        m=json.loads(files['manifest.json'])
        if (set(m)!={'schema_version','role','production_consume','sources','credentials','business_runtime','sha256'} or m.get('schema_version')!=1
                or m.get('role')!=('limited_fc_collector' if role=='node' else 'fc_collection_controller') or m.get('sources')!=['ArabUT','Lootbar']
                or m.get('credentials')!=[] or m.get('business_runtime') is not False or m.get('production_consume') is not False
                or set(m.get('sha256',{}))!=allowed-{'manifest.json'} or any(hashlib.sha256(files[k]).hexdigest()!=v for k,v in m['sha256'].items())):
            raise ValueError('lootbar_role_manifest_invalid')
    return files


def lootbar_access_bytes(raw,expected_sha,old_digest,new_digest):
    if hashlib.sha256(raw).hexdigest()!=expected_sha:raise ValueError('lootbar_access_cas_drift')
    value=json.loads(raw)
    if value.get('worker_digest')!=old_digest or not re.fullmatch('[a-f0-9]{64}',new_digest or ''):raise ValueError('lootbar_worker_digest_drift')
    pattern=rb'("worker_digest"\s*:\s*")'+old_digest.encode()+rb'(")'
    updated,count=re.subn(pattern,lambda m:m[1]+new_digest.encode()+m[2],raw)
    if count!=1 or json.loads(updated)!=dict(value,worker_digest=new_digest):raise ValueError('lootbar_access_field_ambiguous')
    return updated


def _lootbar_old_role(code,role):
    manifest=json.loads((code/'manifest.json').read_text())
    expected=LOOTBAR_ROLE_FILES[role]-{'manifest.json','fc_collection/lootbar.py'}
    actual={p.relative_to(code).as_posix() for p in code.rglob('*') if p.is_file()}
    if (actual!=expected|{'manifest.json'} or set(manifest.get('sha256',{}))!=expected
            or any(p.is_symlink() for p in code.rglob('*'))
            or any(_lootbar_sha(code/n)!=h for n,h in manifest['sha256'].items())):raise ValueError('lootbar_original_role_code_drift')


def lootbar_renderer_window(state,original_task):
    task=next((x for x in state.get('tasks',[]) if x.get('id')==original_task),None)
    if not task or task.get('status') not in ('running','done','error'):raise ValueError('lootbar_original_task_unverified')
    if state.get('workers')!=0:raise ValueError('lootbar_renderer_worker_active')
    if state.get('active_requests',0)!=0:raise ValueError('lootbar_renderer_request_active')


def _lootbar_renderer_state():
    v=json.loads(subprocess.check_output(['docker','inspect','qd-render','--format','{{json .}}'],text=True,timeout=10))
    if v['Image']!=LOOTBAR_RENDERER_IMAGE or v['State']['Running'] is not True:raise ValueError('lootbar_renderer_image_drift')
    if [(x['Source'],x['Destination'],x['RW']) for x in v['Mounts'] if x['Destination']=='/app']!=[('/opt/d4follow','/app',False)]:raise ValueError('lootbar_renderer_mount_drift')
    if v['HostConfig']['PortBindings']!={'9223/tcp':[{'HostIp':'127.0.0.1','HostPort':'9223'}]}:raise ValueError('lootbar_renderer_port_drift')
    if {k:v['HostConfig'][k] for k in LOOTBAR_RENDERER_RESOURCES}!=LOOTBAR_RENDERER_RESOURCES:raise ValueError('lootbar_renderer_resource_drift')
    with urllib.request.urlopen('http://127.0.0.1:8900/api/state',timeout=5) as reply:body=json.load(reply)
    tasks=(body.get('data') or {}).get('tasks',[])
    lines=subprocess.check_output(['docker','top','qd-render','-eo','args'],text=True,timeout=5).splitlines()
    workers=sum('qd_render_svc.py' in x and '--worker' in x for x in lines[1:])
    requests=subprocess.check_output(['ss','-Hnt','state','established','( sport = :9223 )'],text=True,timeout=5).splitlines()
    timer=subprocess.check_output(['systemctl','show','d4follow-collect.timer','--property=ActiveState,SubState,LastTriggerUSec,NextElapseUSecMonotonic,NextElapseUSecRealtime'],text=True,timeout=5)
    listing=subprocess.check_output(['systemctl','list-timers','d4follow-collect.timer','--all','--no-pager','--no-legend'],text=True,timeout=5)
    match=re.match(r'\w+\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(CST|UTC)\b',listing)
    if not match:raise ValueError('lootbar_renderer_next_timer_unverified')
    next_at=datetime.fromisoformat(match[1]+'T'+match[2]).replace(tzinfo=timezone(timedelta(hours=8)) if match[3]=='CST' else timezone.utc)
    return dict(container_id=v['Id'],image_id=v['Image'],pid=v['State']['Pid'],started_at=v['State']['StartedAt'],timer=timer,next_at=next_at.isoformat(),workers=workers,active_requests=len(requests),
                tasks=[{k:t.get(k) for k in ('id','kind','status','started','ended')} for t in tasks],
                resources={k:v['HostConfig'][k] for k in ('Memory','NanoCpus','ShmSize','RestartPolicy')})


def _lootbar_restart_renderer():
    subprocess.run(['docker','restart','--time','10','qd-render'],check=True,timeout=25,stdout=subprocess.DEVNULL)
    deadline=time.monotonic()+10
    while True:
        try:
            with urllib.request.urlopen('http://127.0.0.1:9223/health',timeout=2) as reply:v=json.load(reply)
            if v.get('ok') is True and v.get('svc')=='qd-render':return
        except (OSError,ValueError):pass
        if time.monotonic()>=deadline:raise ValueError('lootbar_renderer_health_failed')
        time.sleep(.2)


def _lootbar_role_health(digest):
    deadline=time.monotonic()+5
    while True:
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
                connection.settimeout(5);connection.connect('/run/fs-fc-collector/worker.sock');connection.sendall(b'{"method":"health"}\n')
                with connection.makefile('rb') as response:value=json.loads(response.readline(65537))
            break
        except (FileNotFoundError,ConnectionRefusedError):
            if time.monotonic()>=deadline:raise
            time.sleep(.1)
    if value.get('worker_digest')!=digest or value.get('uid')!=999:raise ValueError('lootbar_node_health_failed')


def prepare_lootbar(role,bundle,digest,release_id,source_commit,worker_digest=None,original_task=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',release_id or '') or not re.fullmatch('[a-f0-9]{40}',source_commit or ''):raise ValueError('lootbar_release_identity_invalid')
    files=read_lootbar_bundle(bundle,digest,role);root=LOOTBAR_ROOTS[role];code=root if role=='renderer' else root/'code'
    before={name:_lootbar_sha(code/name) for name in files}
    missing={'fc27_lootbar.py','lootbar_background.js'} if role=='renderer' else {'fc_collection/lootbar.py'}
    if {k for k,v in before.items() if v is None}!=missing:raise ValueError('lootbar_exact_new_targets_changed')
    if role!='renderer':
        if before['manifest.json']!=LOOTBAR_BEFORE_MANIFEST[role]:raise ValueError('lootbar_original_manifest_drift')
        actual={p.relative_to(code).as_posix() for p in code.rglob('*') if p.is_file()}
        if actual!=set(files)-missing:raise ValueError('lootbar_original_role_files_drift')
        _lootbar_old_role(code,role)
    elif before['qd_render_svc.py']!=LOOTBAR_RENDERER_BEFORE:raise ValueError('lootbar_original_renderer_source_drift')
    protected=LOOTBAR_RENDERER_PROTECTED if role=='renderer' else LOOTBAR_ROLE_PROTECTED[role]
    m=dict(schema_version=1,scope=LOOTBAR_SCOPE,release_id=release_id,role=role,source_commit=source_commit,
        publisher_sha256=_lootbar_sha(__file__),bundle_name=Path(bundle).name,bundle_sha256=digest,
        before=before,after={n:hashlib.sha256(b).hexdigest() for n,b in files.items()},
        protected={n:_lootbar_sha(n) for n in protected})
    if any(v is None for v in m['protected'].values()):raise ValueError('lootbar_protected_missing')
    if role=='renderer':
        state=_lootbar_renderer_state();lootbar_renderer_window(state,original_task)
        m.update(renderer=state,original_task=original_task)
    elif role=='control':
        access=LOOTBAR_ACCESS;raw=_lootbar_access_read()
        lootbar_access_bytes(raw,_lootbar_sha(access),WORKER,worker_digest)
        m.update(access_before_sha256=_lootbar_sha(access),old_worker_digest=WORKER,worker_digest=worker_digest)
    else:
        if worker_digest!=m['after']['manifest.json']:raise ValueError('lootbar_new_worker_digest_required')
        m['worker_digest']=worker_digest
    return m


def update_lootbar(manifest_path,apply=False,manifest_sha256=None):
    if not re.fullmatch('[a-f0-9]{64}',manifest_sha256 or '') or _lootbar_sha(manifest_path)!=manifest_sha256:raise ValueError('lootbar_manifest_sha256_required')
    m=json.loads(Path(manifest_path).read_text());role=m.get('role')
    if m.get('scope')!=LOOTBAR_SCOPE or m.get('schema_version')!=1 or m.get('publisher_sha256')!=_lootbar_sha(__file__):raise ValueError('lootbar_frozen_manifest_required')
    bundle=Path(manifest_path).parent/m['bundle_name']
    if Path(m['bundle_name']).name!=m['bundle_name']:raise ValueError('lootbar_bundle_path_invalid')
    files=read_lootbar_bundle(bundle,m['bundle_sha256'],role)
    if set(m['before'])!=set(files) or m['after']!={n:hashlib.sha256(b).hexdigest() for n,b in files.items()}:raise ValueError('lootbar_exact_manifest_files_required')
    root=LOOTBAR_ROOTS[role];code=root if role=='renderer' else root/'code'
    if any(p.is_symlink() for p in (root,code,*root.parents)):raise ValueError('lootbar_role_path_link')
    missing={'fc27_lootbar.py','lootbar_background.js'} if role=='renderer' else {'fc_collection/lootbar.py'}
    if {n for n,h in m['before'].items() if h is None}!=missing:raise ValueError('lootbar_exact_new_targets_changed')
    expected_protected=set(LOOTBAR_RENDERER_PROTECTED) if role=='renderer' else set(LOOTBAR_ROLE_PROTECTED[role])
    if set(m['protected'])!=expected_protected or any(not re.fullmatch('[a-f0-9]{64}',h or '') for h in m['protected'].values()):raise ValueError('lootbar_exact_protection_required')
    if role!='renderer' and m['before']['manifest.json']!=LOOTBAR_BEFORE_MANIFEST[role]:raise ValueError('lootbar_original_manifest_drift')
    if role=='renderer' and m['before']['qd_render_svc.py']!=LOOTBAR_RENDERER_BEFORE:raise ValueError('lootbar_original_renderer_source_drift')
    if not re.fullmatch('[a-f0-9]{40}',m.get('source_commit','')):raise ValueError('lootbar_source_commit_required')
    release_id=m['release_id']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',release_id):raise ValueError('lootbar_release_id_invalid')
    receipt=root/('lootbar-'+release_id+'.json');backup=root/('before-lootbar-'+release_id)
    if receipt.exists():
        old=json.loads(receipt.read_text())
        if old.get('phase')=='updated' and old.get('manifest_sha256')==_lootbar_sha(manifest_path) and all(_lootbar_sha(code/n)==h for n,h in m['after'].items()):
            if role=='control' and hashlib.sha256(_lootbar_access_read()).hexdigest()!=old.get('access_after_sha256'):raise ValueError('lootbar_access_after_drift')
            return dict(old,phase='already_updated')
        raise ValueError('lootbar_original_receipt_requires_reconciliation')
    if role!='renderer':_lootbar_old_role(code,role)
    for name,h in m['before'].items():
        if _lootbar_sha(code/name)!=h:raise ValueError('lootbar_target_cas_drift:'+name)
        if h is not None and not _lootbar_root_owned(code/name):raise ValueError('lootbar_target_owner_drift')
    for name,h in m['protected'].items():
        if _lootbar_sha(name)!=h:raise ValueError('lootbar_protected_drift')
    state=None;access=None;old_access=None
    if role=='renderer':
        state=_lootbar_renderer_state();lootbar_renderer_window(state,m['original_task'])
        if any(state[k]!=m['renderer'][k] for k in ('container_id','image_id','resources','timer','next_at')):raise ValueError('lootbar_renderer_baseline_drift')
        if (datetime.fromisoformat(state['next_at'])-datetime.now(timezone.utc)).total_seconds()<45:raise ValueError('lootbar_renderer_window_too_short')
    elif role=='node':
        if list(LOOTBAR_SPOOL.iterdir()):raise ValueError('lootbar_original_spool_not_empty')
    else:
        access=LOOTBAR_ACCESS;old_access=_lootbar_access_read()
        new_access=lootbar_access_bytes(old_access,m['access_before_sha256'],m['old_worker_digest'],m['worker_digest'])
    result=dict(scope=LOOTBAR_SCOPE,role=role,release_id=release_id,manifest_sha256=_lootbar_sha(manifest_path),phase='preview',files=len(files),backup=str(backup))
    if role=='control':result['access_after_sha256']=hashlib.sha256(new_access).hexdigest()
    if backup.exists() or backup.is_symlink() or (root/('failed-lootbar-'+release_id)).exists():raise ValueError('lootbar_existing_backup_requires_reconciliation')
    if not apply:return result
    if os.geteuid()!=0 or socket.gethostname()!=('play187' if role=='control' else 'FSHTUS01'):raise ValueError('lootbar_original_host_required')
    switched=False;written=[];candidate=None;stopped=False
    try:
        if role=='renderer':
            backup.mkdir(mode=0o700)
            for n,h in m['before'].items():
                if h is not None:(backup/n).write_bytes((code/n).read_bytes())
            for n,body in files.items():atomic(code/n,body,0o644);written.append(n)
            _lootbar_restart_renderer();after=_lootbar_renderer_state()
            if any(after[k]!=state[k] for k in ('container_id','image_id','resources','timer','next_at')):raise ValueError('lootbar_renderer_or_timer_changed')
            if after['started_at']==state['started_at'] or after['pid']==state['pid']:raise ValueError('lootbar_renderer_not_reloaded')
            old_task=next(x for x in state['tasks'] if x['id']==m['original_task'])
            new_task=next((x for x in after['tasks'] if x['id']==m['original_task']),None)
            if not new_task or any(old_task.get(k)!=new_task.get(k) for k in ('id','kind','started')):raise ValueError('lootbar_original_rpg_task_lost')
        else:
            candidate=Path(tempfile.mkdtemp(prefix='.lootbar-code-',dir=str(root)));candidate.chmod(0o755)
            for n,body in files.items():
                p=candidate/n;p.parent.mkdir(parents=True,exist_ok=True,mode=0o755);p.parent.chmod(0o755);p.write_bytes(body);p.chmod(0o444)
            if role=='node':
                subprocess.run(['systemctl','stop','fs-fc-collector.service'],check=True,timeout=15);stopped=True
            code.rename(backup);candidate.rename(code);switched=True
            if role=='control':atomic(access,new_access,0o600)
            else:
                subprocess.run(['systemctl','start','fs-fc-collector.service'],check=True,timeout=15)
                _lootbar_role_health(m['worker_digest'])
        if any(_lootbar_sha(code/n)!=h for n,h in m['after'].items()) or any(_lootbar_sha(n)!=h for n,h in m['protected'].items()):raise ValueError('lootbar_postwrite_readback_failed')
        if role=='control' and _lootbar_access_read()!=new_access:raise ValueError('lootbar_access_after_drift')
        result.update(phase='updated',backup=str(backup));atomic(receipt,(json.dumps(result,sort_keys=True)+'\n').encode(),0o600)
        return result
    except BaseException:
        if role=='renderer':
            for n in reversed(written):
                if _lootbar_sha(code/n)!=m['after'][n]:raise ValueError('lootbar_rollback_target_drift')
                if m['before'][n] is None:(code/n).unlink()
                else:atomic(code/n,(backup/n).read_bytes(),0o644)
            if written:_lootbar_restart_renderer()
        elif switched:
            if role=='node':subprocess.run(['systemctl','stop','fs-fc-collector.service'],check=True,timeout=15)
            code.rename(root/('failed-lootbar-'+release_id));backup.rename(code)
            if old_access is not None:
                if access.read_bytes() not in (old_access,new_access):raise ValueError('lootbar_rollback_access_drift')
                atomic(access,old_access,0o600)
        elif role!='renderer' and backup.exists() and not code.exists():
            backup.rename(code)
        if role=='node' and stopped:
            subprocess.run(['systemctl','start','fs-fc-collector.service'],check=True,timeout=15)
            _lootbar_role_health(m['before']['manifest.json'])
        result['phase']='rolled_back';atomic(receipt,(json.dumps(result,sort_keys=True)+'\n').encode(),0o600)
        raise


if __name__ == '__main__' and len(sys.argv)>1 and sys.argv[1]=='lootbar-prepare':
    p=argparse.ArgumentParser(description='Read-only fresh exact CAS manifest; prints hashes only')
    p.add_argument('--role',choices=('node','control','renderer'),required=True);p.add_argument('--bundle',required=True)
    p.add_argument('--bundle-sha256',required=True);p.add_argument('--release-id',required=True);p.add_argument('--source-commit',required=True)
    p.add_argument('--worker-digest');p.add_argument('--original-task')
    a=p.parse_args(sys.argv[2:]);print(json.dumps(prepare_lootbar(a.role,a.bundle,a.bundle_sha256,a.release_id,a.source_commit,a.worker_digest,a.original_task),sort_keys=True))
elif __name__ == '__main__' and len(sys.argv)>1 and sys.argv[1]=='lootbar':
    p=argparse.ArgumentParser(description='Exact Lootbar source-role/renderer update; legacy 11/7 mode unchanged')
    p.add_argument('--manifest',required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--apply',action='store_true')
    a=p.parse_args(sys.argv[2:]);print(json.dumps(update_lootbar(a.manifest,a.apply,a.manifest_sha256),sort_keys=True))
elif __name__ == '__main__':
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('bundle', type=Path)
    parser.add_argument('sha256')
    parser.add_argument('worker_digest')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(update(args.bundle, args.sha256, args.worker_digest, args.apply), sort_keys=True))
