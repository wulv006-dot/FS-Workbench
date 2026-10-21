"""Two-phase update of the existing 8767 owner; preserve its current checkpoint."""
import fcntl, hashlib, json, os, subprocess, sys, time
from pathlib import Path
from patch_paid import transform

OP = 'fs-admin-monthly-paid-20261021-v1'
BACKUP = Path('/var/backups') / OP
UNIT = Path('/etc/systemd/system/fc27-p2pah-session.service')
BASE = 'fc27-cloud-session:ocr-chenchao-20261021-v1'
BASE_ID = 'sha256:0a203583d058ef27a6989e6e10f3d12d3e31c8e69f8a00eae3196bac56778b7f'
IMAGE = 'fc27-cloud-session:monthly-paid-20261021-v1'
SOURCE_SHA = 'e711cb9fcaf9c2cdc03af1d28619895dc7f391aaa7f8b4cc3846fca5fc6a3663'
SERVICE_SHA = '52577a17418f05c1fe4adfb9a672595f39258e8750cfbfcc8154d127b1ffca01'

def run(*args):
    return subprocess.check_output(args, text=True)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def local(path):
    import urllib.request
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8767'+path, timeout=12) as r:
        return json.load(r)

def unit_patch(source):
    if source.count(BASE) != 1 or source.count('dst=/run/secrets/fs-session-state') != 1:
        raise RuntimeError('admin_unit_changed')
    return source.replace(BASE, IMAGE, 1)

def checkpoint():
    health, session = local('/health'), local('/session/admin-token')
    if not health.get('ready') or not session.get('ready'):
        raise RuntimeError('existing_global_session_not_ready')
    p=Path('/run/fs-admin-session-state/session.json'); st=p.lstat()
    import stat
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or st.st_mode & 0o077 or st.st_size > 32768:
        raise RuntimeError('checkpoint_unsafe')
    value=json.loads(p.read_bytes())
    if value.get('token') != session.get('token') or not 0 <= time.time()-value.get('created',0) <= 1500:
        raise RuntimeError('current_checkpoint_not_fresh_wait_for_global_owner')
    if value.get('login_attempts') != health.get('login_attempts'):
        raise RuntimeError('checkpoint_attempts_changed')
    return health, session['token']

def record(receipt):
    target=BACKUP/'receipt.json'; temporary=BACKUP/'receipt.new'
    temporary.write_text(json.dumps(receipt,indent=2)); temporary.chmod(0o600)
    os.replace(temporary,target)

def prepare(resume=False):
    assert BACKUP.exists() == resume, 'existing operation requires readback'
    assert run('docker','inspect','--format','{{.Image}}','fc27-p2pah-session').strip() == BASE_ID
    assert run('docker','image','inspect',BASE,'--format','{{.Id}}').strip() == BASE_ID
    unit=UNIT.read_text(); unit_patch(unit)
    source=run('docker','exec','fc27-p2pah-session','cat','/usr/local/bin/cohort_paid_source.py')
    assert digest(source.encode()) == SOURCE_SHA
    service=run('docker','exec','fc27-p2pah-session','cat','/usr/local/bin/p2pah_session_service.py')
    assert digest(service.encode()) == SERVICE_SHA
    checkpoint()
    if not resume:
        assert subprocess.run(['docker','image','inspect',IMAGE],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode != 0
        BACKUP.mkdir(mode=0o700)
        (BACKUP/'unit').write_text(unit); (BACKUP/'unit').chmod(0o600)
    else:
        assert (BACKUP/'unit').read_text() == unit and not (BACKUP/'receipt.json').exists(), 'resume_state_changed'
    context=BACKUP/'candidate'
    if not resume:context.mkdir(mode=0o700)
    candidate=transform(source)
    helper=Path(__file__).with_name('monthly_paid.py').read_bytes()
    if resume:
        assert (context/'cohort_paid_source.py').read_text() == candidate and (context/'monthly_paid.py').read_bytes() == helper
    else:
        (context/'cohort_paid_source.py').write_text(candidate)
        (context/'monthly_paid.py').write_bytes(helper)
        (context/'Dockerfile').write_text('FROM '+BASE+'\nCOPY cohort_paid_source.py monthly_paid.py /usr/local/bin/\nRUN python3 -m py_compile /usr/local/bin/cohort_paid_source.py /usr/local/bin/monthly_paid.py\n')
        subprocess.run(['docker','build','--network=none','-q','-t',IMAGE,str(context)],check=True)
    assert run('docker','image','inspect',BASE,'--format','{{.Id}}').strip() == BASE_ID
    subprocess.run(['docker','run','--rm','--network=none','--read-only','--entrypoint','python3',IMAGE,'-B','-c',"import sys;sys.path.insert(0,'/usr/local/bin');import cohort_paid_source,monthly_paid;assert callable(cohort_paid_source.collect)"],check=True)
    receipt=dict(operation=OP,state='PREPARED',unit_before=digest(UNIT.read_bytes()),base=BASE,base_id=BASE_ID,image=IMAGE,
        image_id=run('docker','image','inspect',IMAGE,'--format','{{.Id}}').strip(),source_before=SOURCE_SHA,
        source_after=digest(candidate.encode()),helper_sha256=digest(helper),service_unchanged=SERVICE_SHA)
    record(receipt);print(json.dumps(receipt))

def switch(rollback=False):
    receipt=json.loads((BACKUP/'receipt.json').read_bytes())
    expected='DEPLOYED_READY' if rollback else 'PREPARED'
    assert receipt['state'] == expected, 'unknown operation state requires inspection'
    assert digest(UNIT.read_bytes()) == receipt['unit_after' if rollback else 'unit_before']
    assert run('docker','inspect','--format','{{.Image}}','fc27-p2pah-session').strip() == (receipt['image_id'] if rollback else BASE_ID)
    health,token=checkpoint()
    if health.get('active_model_reads') or health.get('active_customer_reads'):
        raise RuntimeError('active_query_wait')
    if subprocess.run(['systemctl','is-active','sales-dashboard-sync'],capture_output=True,text=True).stdout.strip() in ('active','activating'):
        raise RuntimeError('sales_sync_busy_wait')
    before=UNIT.read_text()
    updated=(BACKUP/'unit').read_text() if rollback else unit_patch(before)
    receipt.update(state='ROLLBACK_STARTED' if rollback else 'CUTOVER_STARTED');record(receipt)
    temporary=UNIT.with_suffix('.monthly-new');temporary.write_text(updated);temporary.chmod(0o644)
    assert UNIT.read_text() == before, 'concurrent_unit_change'
    os.replace(temporary,UNIT)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','restart','fc27-p2pah-session'],check=True)
    final=None
    for _ in range(45):
        try:
            final=local('/health')
            if final.get('ready'):break
        except (OSError,ValueError):pass
        time.sleep(1)
    current=local('/session/admin-token')
    assert final and final.get('ready') and current.get('token') == token, 'session_readback_failed'
    assert final['login_attempts'] == health['login_attempts'], 'unexpected_password_login'
    service=run('docker','exec','fc27-p2pah-session','cat','/usr/local/bin/p2pah_session_service.py')
    assert digest(service.encode()) == SERVICE_SHA
    actual=run('docker','exec','fc27-p2pah-session','cat','/usr/local/bin/cohort_paid_source.py')
    assert digest(actual.encode()) == (SOURCE_SHA if rollback else receipt['source_after'])
    receipt.update(state='ROLLED_BACK_READY' if rollback else 'DEPLOYED_READY',unit_after=digest(UNIT.read_bytes()),
        same_access_token=True,login_attempts_before=health['login_attempts'],login_attempts_after=final['login_attempts'],health=final)
    record(receipt); print(json.dumps(receipt))

if __name__ == '__main__':
    with open('/run/lock/fs-admin-session-unify.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if sys.argv[1:] == ['prepare']:prepare()
        elif sys.argv[1:] == ['resume-prepare']:prepare(True)
        elif sys.argv[1:] == ['switch']:switch()
        elif sys.argv[1:] == ['rollback']:switch(True)
        else:raise RuntimeError('expected_prepare_switch_or_rollback')
