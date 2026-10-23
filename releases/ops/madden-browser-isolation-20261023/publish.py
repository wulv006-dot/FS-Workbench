"""One Madden release through the installed house atomic publisher; no business jobs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path('/opt/madden-workbench')
STAGE = Path(__file__).resolve().parent
BACKUP = Path('/var/backups/madden-browser-isolation-20261023')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def verify(root, stage, manifest):
    for name, item in manifest.items():
        if name not in ('dashboard/server.py', 'madden_nfl_27/browser.py',
                        'browser_runtime.py', 'run_in_container.sh'):
            raise ValueError('target_not_allowlisted')
        if sha(root/name) != item['before'] or sha(stage/'source'/name) != item['after']:
            raise RuntimeError('source_or_runtime_changed:' + name)


def call(args):
    return subprocess.run(args, capture_output=True, text=True, check=True, timeout=30).stdout


def main():
    import fcntl
    manifest = json.loads((STAGE/'manifest.json').read_text())
    verify(ROOT, STAGE, manifest)
    with urllib.request.urlopen('http://127.0.0.1:8792/api/madden/cloud/health', timeout=8) as r:
        health = json.load(r)
    assert health['queue_depth'] == 0 and health['incomplete_executions'] == 0
    assert health['tab_count'] == 0 and health['system_enabled'] and health['mode'] == 'auto'
    cfg=json.loads((ROOT/'evidence/automation.json').read_text())
    assert cfg['revision']==19 and cfg['interval_minutes']==240 and cfg['pricing_revision']==7
    sys.path.insert(0, '/opt/fs-hermes-ops')
    from host import publisher
    atomic = publisher().atomic
    assert not BACKUP.exists(), 'existing_release_receipt_requires_readback'
    BACKUP.mkdir(mode=0o700)
    receipt={'operation_id':'madden-browser-isolation-20261023','status':'prepared','files':manifest}
    atomic(BACKUP/'receipt.json',json.dumps(receipt).encode(),0o600)
    # Missing bind source must be restored before the original container is stopped.
    startup = ROOT/'madden-browser-start.sh'
    assert not startup.exists()
    original = subprocess.run(['docker','exec','madden-cloud-browser','cat',
                               '/usr/local/bin/madden-browser-start'],capture_output=True,check=True,timeout=10).stdout
    assert hashlib.sha256(original).hexdigest()=='12fca545ea0e65ae3d6df8102f6bc43753f6338aa646284d7d0398069f679341'
    atomic(startup, original, 0o755)
    call(['systemctl','stop','madden-workbench.service'])
    with open(ROOT/'evidence/browser-job.lock','a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        verify(ROOT,STAGE,manifest)
        active=call(['docker','ps','-q','--filter','name=^madden-job-']).strip()
        assert not active, 'active_worker_preserved'
        for name,item in manifest.items():
            target=ROOT/name
            if target.exists():
                backup=BACKUP/name;backup.parent.mkdir(parents=True,exist_ok=True)
                atomic(backup,target.read_bytes(),0o600)
        call(['docker','stop','--time','10','madden-cloud-browser'])
        call(['docker','update','--memory','3g','--memory-swap','3g',
              '--restart','no','madden-cloud-browser'])
        for name,item in manifest.items():
            target=ROOT/name
            assert sha(target)==item['before']
            atomic(target,(STAGE/'source'/name).read_bytes(),0o755 if name.endswith('.sh') else 0o644)
            assert sha(target)==item['after']
        receipt.update(status='published_sha_verified',startup_restored=True,
                       competitor_memory_bytes=3*1024**3,worker_memory_bytes=2*1024**3,
                       business_jobs_created=0)
        atomic(BACKUP/'receipt.json',json.dumps(receipt).encode(),0o600)
    call(['systemctl','start','madden-workbench.service'])
    print(json.dumps(receipt))


if __name__=='__main__':
    import fcntl
    with open('/var/lock/fs-navigation-release.lock','a+b') as nav, open('/var/lock/fs-dashboard-release.lock','a+b') as dashboard:
        fcntl.flock(nav,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(dashboard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        main()
