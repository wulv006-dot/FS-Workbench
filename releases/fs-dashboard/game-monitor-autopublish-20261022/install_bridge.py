"""Install the merged bounded extension under the existing bridge lock and backup."""
import hashlib,json,os,shutil,sys
from pathlib import Path

STAGE=Path(__file__).resolve().parent
OPS=Path('/opt/fs-hermes-ops')
STATE=Path('/var/lib/fs-hermes-ops/game-monitor')
PROFILE=Path('/var/lib/fs-hermes-fc/profile/game-monitor-maintenance')

def sha(raw):return hashlib.sha256(raw).hexdigest()
def safe(path,trusted=True):
    for item in (path,*path.parents):
        assert not item.is_symlink(),'linked_install_path'
        if item.exists():
            info=item.stat()
            if trusted:assert info.st_uid==0 and not info.st_mode&0o022,'unsafe_install_owner'
            else:assert item.is_dir(),'profile_directory_required'

def main():
    import fcntl
    sys.path.insert(0,str(OPS))
    from release_navigation_base import atomic
    assert os.geteuid()==0
    approval=json.loads((STAGE/'install-manifest.json').read_bytes())
    assert set(approval['files'])=={'contract.py','controller.py','publication.py','jsparse.py','host.py'}
    for name,digest in approval['files'].items():assert sha((STAGE/name).read_bytes())==digest
    safe(OPS);safe(STATE);safe(PROFILE,trusted=False)
    backup=Path('/var/backups/fs-hermes-ops-game-monitor-20261022');safe(backup)
    assert not backup.exists(),'reconcile_original_install_first'
    before=(OPS/'host.py').read_bytes();assert sha(before)=='2aef3f6a761e08a595648aeffc1ae602a6f1ac694e82c1703ff42784455dc356'
    old=before.decode();new=(STAGE/'host.py').read_bytes().decode()
    needle="        write(PROFILE/'snapshot.json', collect(now))"
    hook="\n        try:\n            result = subprocess.run(['/opt/python39/bin/python3', '-B', str(HERE/'game_monitor/controller.py')], capture_output=True, text=True, timeout=100)\n            if result.returncode: print('game-monitor auto-publication needs attention; inspect its preserved status', flush=True)\n        except subprocess.TimeoutExpired:\n            print('game-monitor step timed out; reconcile its original journal on the next tick', flush=True)"
    assert old.count(needle)==1 and new==old.replace(needle,needle+hook),'existing_bridge_logic_changed'
    with Path('/var/lib/fs-hermes-ops/lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert (OPS/'host.py').read_bytes()==before
        backup.mkdir(mode=0o700)
        atomic(backup/'host.py',before,0o600)
        atomic(backup/'install-manifest.json',(STAGE/'install-manifest.json').read_bytes(),0o600)
        package=OPS/'game_monitor';assert not package.exists(),'existing_module_reconcile_required'
        package.mkdir(mode=0o755);STATE.mkdir(mode=0o700)
        for name in ('contract.py','controller.py','publication.py','jsparse.py'):atomic(package/name,(STAGE/name).read_bytes(),0o644)
        for name in ('contract.py','controller.py','publication.py','jsparse.py'):assert sha((package/name).read_bytes())==approval['files'][name]
        atomic(OPS/'host.py',(STAGE/'host.py').read_bytes(),0o644)
        assert sha((OPS/'host.py').read_bytes())==approval['files']['host.py']
        atomic(STATE/'installation.json',json.dumps(approval,indent=2).encode(),0o600)
    print(json.dumps(dict(installed=True,backup=str(backup),original_bridge_preserved=True,new_timers=0,business_services_restarted=0,merge=approval['merge'])))

if __name__=='__main__':main()
