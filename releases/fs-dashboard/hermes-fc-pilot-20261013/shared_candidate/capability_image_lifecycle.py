"""Image lifecycle leaf for the existing publisher; no CLI or agent tool.

Only invoked under the publisher's release/admission/collector/provider locks.
Build from a seven-file code-only context; journal image intent before tag CAS.
"""
import hashlib,json,re,subprocess,time,urllib.request
from pathlib import Path

IMAGE=re.compile(r'^sha256:[a-f0-9]{64}$')
ROOT='/opt/fc27-cloud/marketing-session-20261009'
TAG='fc27-cloud-session:business-live-20261010'
BASE='fc27-cloud-session:traffic-20261009-ec4c7ba41c3c'
PACKAGE=('__init__.py','capabilities.py','admin_session_entry.py')
UNIT='fc27-p2pah-session.service'

def image_id(tag):
    value=subprocess.check_output(['docker','image','inspect','-f','{{.Id}}',tag],text=True).strip()
    if not IMAGE.fullmatch(value):raise ValueError('invalid session image identity')
    return value

def baseline(manifest):
    if image_id(TAG)!=manifest['sessionCurrentImage'] or image_id(BASE)!=manifest['sessionBaseImage']:
        raise ValueError('capability session image baseline drift')
    value=json.loads(subprocess.check_output(['docker','inspect','fc27-p2pah-session'],text=True))[0]
    if value['Image']!=manifest['sessionCurrentImage'] or value['Config']['Image']!=TAG:
        raise ValueError('running session image differs from pinned tag')

def restart_health(expected_image):
    subprocess.run(['systemctl','restart',UNIT],check=True)
    subprocess.run(['systemctl','is-active','--quiet',UNIT],check=True)
    for attempt in range(90):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8767/health',timeout=2) as response:value=json.load(response)
            if value.get('ready') is True or value.get('status')=='ready':break
        except (OSError,ValueError):pass
        time.sleep(1)
    else:raise ValueError('capability session health unavailable')
    actual=json.loads(subprocess.check_output(['docker','inspect','fc27-p2pah-session'],text=True))[0]
    if actual['Image']!=expected_image:raise ValueError('session running image readback differs')

def apply(manifest,backup,journal,root,atomic,journal_write,digest,no_target_link):
    baseline(manifest)
    source=root/ROOT.lstrip('/')
    protected={r['path']:r['sha256'] for r in manifest['unchangedRequired']}
    desired={r['target']:r['sha256'] for r in manifest['files']}
    names=['p2pah_session_service.py','admin_summary.py','supplement_fields.py']+['admin_order_capabilities_20261014/'+n for n in PACKAGE]
    context=backup/'session-build'
    if context.exists():raise ValueError('existing session build context; reconcile journal before retry')
    context.mkdir(mode=0o700)
    expected={}
    for name in names+['Dockerfile.session']:
        path=source/name;no_target_link(path)
        sha=desired.get(str(path)) if root==Path('/') else desired.get(ROOT+'/'+name)
        sha=sha or protected.get(ROOT+'/'+name)
        if not sha or digest(path)!=sha:raise ValueError('session build source drift')
        atomic(context/name,path.read_bytes(),0o600)
        if name!='Dockerfile.session':expected['/usr/local/bin/'+name]=sha
    # Unique release tag never changes the running tag during build/verification.
    tag='fc27-cloud-session:capability-'+manifest['sourceCommit'][:12]+'-'+backup.name[4:]
    journal['sessionBuildTag']=tag;journal_write(backup,journal)
    subprocess.run(['docker','build','--network','none','--pull=false','-f',str(context/'Dockerfile.session'),'-t',tag,str(context)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    built=image_id(tag)
    output=subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','sha256sum',tag]+list(expected),text=True)
    actual={line.split()[1]:line.split()[0] for line in output.splitlines()}
    if actual!=expected:raise ValueError('built capability session source mismatch')
    baseline(manifest)
    journal['sessionBuiltImage']=built;journal['sessionImageIntent']=True;journal_write(backup,journal)
    if image_id(TAG)!=journal['sessionImageBefore']:raise ValueError('session tag drift before switch')
    subprocess.run(['docker','tag',built,TAG],check=True)
    if image_id(TAG)!=built:raise ValueError('session tag switch readback differs')
    journal['sessionImageWritten']=True;journal_write(backup,journal)
    restart_health(built)

def restore(backup,journal,journal_write):
    if not journal.get('sessionImageIntent'):return
    old=journal.get('sessionImageBefore');new=journal.get('sessionBuiltImage')
    if not IMAGE.fullmatch(old or '') or not IMAGE.fullmatch(new or ''):raise ValueError('session rollback identity missing')
    actual=image_id(TAG)
    if actual not in (old,new):raise ValueError('session rollback tag drift; preserve images and journal')
    journal['sessionImageRollbackIntent']=True;journal_write(backup,journal)
    if actual==new:subprocess.run(['docker','tag',old,TAG],check=True)
    if image_id(TAG)!=old:raise ValueError('session rollback tag readback differs')
    restart_health(old)
    journal['sessionImageWritten']=False;journal['sessionImageRestored']=True;journal_write(backup,journal)
