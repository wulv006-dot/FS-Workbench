"""Three-file image leaf. Called only inside the inherited publisher locks/journal."""
import hashlib,json,os,re,shutil,stat,subprocess,time,urllib.request
from pathlib import Path

BASE_IMAGE='sha256:88963f9429c84615a7ba24623cf0f54a7d4c313644c64092098e0adb52e835d8'
OLD_TAG='fc27-cloud-session:business-live-20261010'
NEW_TAG='fc27-cloud-session:traffic-hermes-20261017-es'
SESSION_ROOT='/opt/fc27-cloud/marketing-session-20261009'
ARCHIVE='/var/lib/fc27-es-exports'
UNIT='fc27-p2pah-session.service'
NAMES=('p2pah_session_service.py','es_order_structure.py','traffic_contract.py')
IMAGE=re.compile(r'sha256:[a-f0-9]{64}')


def image_id(tag,missing=False):
    result=subprocess.run(['docker','image','inspect','-f','{{.Id}}',tag],capture_output=True,text=True,timeout=15)
    if result.returncode:
        if missing and 'No such image' in result.stderr:return None
        raise ValueError('session_image_inspection_failed')
    value=result.stdout.strip()
    if not IMAGE.fullmatch(value):raise ValueError('session_image_identity')
    return value


def running(missing=False):
    response=subprocess.run(['docker','inspect','fc27-p2pah-session'],capture_output=True,text=True,timeout=15)
    if response.returncode:
        if missing and ('No such object' in response.stderr or 'No such container' in response.stderr):return None
        raise ValueError('session_container_inspection_failed')
    data=json.loads(response.stdout)
    if len(data)!=1:raise ValueError('session_container_identity')
    return data[0]


def archive_boundary(root,create=False):
    path=root/ARCHIVE.lstrip('/')
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('archive_path_link')
    if not path.exists() and create:path.mkdir(mode=0o700)
    if path.exists():
        info=path.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('archive_directory_boundary')
    if shutil.disk_usage(path if path.exists() else path.parent).free<64*1024*1024:raise ValueError('archive_disk_reserve')


def baseline(manifest,root):
    if manifest.get('sessionBaseImage')!=BASE_IMAGE or manifest.get('sessionCurrentImage')!=BASE_IMAGE or manifest.get('sessionNewTag')!=NEW_TAG:raise ValueError('exact_session_image_contract')
    if image_id(BASE_IMAGE)!=BASE_IMAGE or image_id(OLD_TAG)!=BASE_IMAGE:raise ValueError('session_image_baseline_drift')
    value=running()
    if not value or value['Image']!=BASE_IMAGE or value['Config']['Image']!=OLD_TAG:raise ValueError('session_container_baseline_drift')
    archive_boundary(root)
    if image_id(NEW_TAG,True) is not None:raise ValueError('new_session_tag_exists_requires_reconcile')


def restart_health(expected,archive=False):
    subprocess.run(['systemctl','daemon-reload'],check=True,timeout=15)
    subprocess.run(['systemctl','restart',UNIT],check=True,timeout=45)
    subprocess.run(['systemctl','is-active','--quiet',UNIT],check=True,timeout=10)
    for attempt in range(90):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8767/health',timeout=2) as response:health=json.load(response)
            if health.get('ready') is True or health.get('status')=='ready':break
        except (OSError,ValueError):pass
        time.sleep(1)
    else:raise ValueError('session_health_not_ready')
    value=running()
    if not value or value['Image']!=expected:raise ValueError('session_running_image_readback')
    if archive:
        mounts=[m for m in value.get('Mounts',[]) if m.get('Destination')==ARCHIVE]
        if len(mounts)!=1 or mounts[0].get('Source')!=ARCHIVE or mounts[0].get('RW') is not True:raise ValueError('session_archive_mount_readback')


def apply(manifest,backup,journal,root,atomic,journal_write,digest,no_target_link):
    if journal.get('sessionBuildIntent'):raise ValueError('session_build_previous_intent_requires_reconcile')
    baseline(manifest,root);archive_boundary(root,True)
    source=root/SESSION_ROOT.lstrip('/');context=backup/'session-build'
    if context.exists():raise ValueError('session_build_context_exists')
    context.mkdir(mode=0o700)
    desired={r['target']:r['sha256'] for r in manifest['files']};expected={}
    for name in (*NAMES,'Dockerfile.session'):
        path=source/name;no_target_link(path)
        if digest(path)!=desired.get(SESSION_ROOT+'/'+name):raise ValueError('session_build_source_drift')
        atomic(context/name,path.read_bytes(),0o600)
        if name in NAMES:expected['/usr/local/bin/'+name]=desired[SESSION_ROOT+'/'+name]
    journal.update(sessionImageBefore=BASE_IMAGE,sessionBuildTag=NEW_TAG,sessionBuildIntent=True);journal_write(backup,journal)
    try:
        subprocess.run(['docker','build','--network','none','--pull=false','--build-arg','SESSION_BASE_IMAGE='+BASE_IMAGE,'-f',str(context/'Dockerfile.session'),'-t',NEW_TAG,str(context)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,env={**os.environ,'DOCKER_BUILDKIT':'0'})
        built=image_id(NEW_TAG)
        journal.update(sessionBuiltImage=built,sessionBuildOutcome='built_unverified');journal_write(backup,journal)
        raw=subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','sha256sum',NEW_TAG,*expected],text=True,timeout=45)
        if {line.split()[1]:line.split()[0] for line in raw.splitlines()}!=expected:raise ValueError('built_session_source_sha_mismatch')
    except subprocess.CalledProcessError as error:
        # Keep raw builder diagnostics private; the public error contains no output.
        output=error.stdout or b'';stderr=error.stderr or b''
        if isinstance(output,str):output=output.encode('utf-8',errors='replace')
        if isinstance(stderr,str):stderr=stderr.encode('utf-8',errors='replace')
        payload=b'stdout\n'+output+b'\nstderr\n'+stderr
        diagnostic=backup/'session-build-failure.log'
        atomic(diagnostic,payload,0o600)
        journal.update(sessionBuildOutcome='FAILED',sessionBuildExitCode=error.returncode,sessionBuildDiagnostic=str(diagnostic),sessionBuildDiagnosticSha256=hashlib.sha256(payload).hexdigest())
        journal_write(backup,journal)
        raise ValueError('session_build_or_verify_failed_private_diagnostic_requires_reconcile') from None
    except subprocess.TimeoutExpired:
        journal['sessionBuildOutcome']='UNKNOWN';journal_write(backup,journal);raise ValueError('session_build_or_verify_unknown_requires_reconcile')
    # The old tag remains unchanged. The candidate unit switches to the new tag.
    if image_id(OLD_TAG)!=BASE_IMAGE or image_id(NEW_TAG)!=built or running()['Image']!=BASE_IMAGE:raise ValueError('session_drift_before_restart')
    journal.update(sessionBuiltImage=built,sessionRestartIntent=True);journal_write(backup,journal)
    try:restart_health(built,True)
    except subprocess.TimeoutExpired:
        journal['sessionRestartOutcome']='UNKNOWN';journal_write(backup,journal);raise ValueError('session_restart_unknown_requires_reconcile')
    journal['sessionImageWritten']=True;journal_write(backup,journal)


def restore(backup,journal,root,journal_write):
    if not journal.get('sessionBuildIntent'):return
    value=running(missing=True);allowed={BASE_IMAGE,journal.get('sessionBuiltImage')}
    if value and value['Image'] not in allowed:raise ValueError('session_rollback_external_image_drift')
    if image_id(OLD_TAG)!=BASE_IMAGE:raise ValueError('session_rollback_old_tag_drift')
    journal['sessionRollbackIntent']=True;journal_write(backup,journal)
    restart_health(BASE_IMAGE)
    journal['sessionImageRestored']=True;journal_write(backup,journal)
    # Archive originals, cache attempts and built images remain for reconciliation.
