"""Install this exact reviewed module; preserve every unrelated file and service."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

STAGE = Path(__file__).resolve().parent
ROOT = Path('/opt/fs-hermes-ops')
PROFILE = Path('/var/lib/fs-hermes-fc/profile/ops-watchdog')
MAP = {**{name: ROOT/name for name in ('common.py','github_api.py','host.py','watch.py','release_ui.py','release_navigation_base.py','publish_monitor.py')},
       'monitor-health-hooks.py': ROOT/'recipes/monitor-health/hooks.py',
       'fs-hermes-ops-bridge.service': Path('/etc/systemd/system/fs-hermes-ops-bridge.service'),
       'fs-hermes-ops-bridge.timer': Path('/etc/systemd/system/fs-hermes-ops-bridge.timer'),
       'watch.py.profile': Path('/var/lib/fs-hermes-fc/profile/scripts/fs-ops-watchdog/watch.py'),
       'common.py.profile': Path('/var/lib/fs-hermes-fc/profile/scripts/fs-ops-watchdog/common.py'),
       'SKILL.md': Path('/var/lib/fs-hermes-fc/profile/skills/fs-operations/fs-ops-watchdog/SKILL.md'),
       'private-target.json': PROFILE/'private-target.json'}

def main():
    if os.geteuid() != 0: raise ValueError('root_required')
    approved = json.loads((STAGE/'install-manifest.json').read_text())
    if set(approved) != set(MAP): raise ValueError('exact_install_scope_required')
    for name, target in MAP.items():
        if hashlib.sha256((STAGE/name).read_bytes()).hexdigest() != approved[name]: raise ValueError('staged_source_drift')
        if any(p.is_symlink() for p in (target,*target.parents)): raise ValueError('linked_install_target')
        if target.exists() and target.read_bytes() != (STAGE/name).read_bytes(): raise ValueError('existing_install_drift:'+name)
        if target.exists() and (target.stat().st_uid != 0 or target.stat().st_mode & 0o022 or target.stat().st_nlink != 1): raise ValueError('unsafe_existing_file:'+name)
    for parent in (ROOT, *ROOT.parents):
        if parent.exists() and (parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022): raise ValueError('unsafe_runtime_parent')
    for name, target in MAP.items():
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not target.exists():
            with target.open('xb') as stream: stream.write((STAGE/name).read_bytes()); stream.flush(); os.fsync(stream.fileno())
            os.chmod(target, 0o600 if name == 'private-target.json' else 0o644)
    state=Path('/var/lib/fs-hermes-ops'); state.mkdir(mode=0o700,exist_ok=True)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','start','fs-hermes-ops-bridge.service'],check=True)
    subprocess.run(['systemctl','enable','--now','fs-hermes-ops-bridge.timer'],check=True)
    if any(hashlib.sha256(target.read_bytes()).hexdigest()!=approved[name] for name,target in MAP.items()): raise ValueError('installed_readback_drift')
    print(json.dumps({'installed_files':len(MAP),'timer':'fs-hermes-ops-bridge.timer','business_services_restarted':False,'source_readback':'verified'}))

if __name__=='__main__':main()
