"""Scoped adapter of the existing publisher; retains CAS, locks, backup and rollback."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

HERE=Path(__file__).resolve().parent
BASE=Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
SCOPE='gravitec-webpush-20261103'
TARGETS={'market_worker.py':'/opt/marketing-worker/market_worker.py',
         'webpush.py':'/opt/marketing-worker/webpush.py',
         'marketing.html':'/opt/marketing-worker/web/marketing.html'}

def publisher():
    source=BASE/'release_source_tabs.py'
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!='78b4b054162a9cf578543f11bc6cea3b0041b535d49ea1c8f6059514f90e3466':
        raise ValueError('existing publisher changed')
    module=types.ModuleType('webpush_existing_publisher');module.__file__=str(source)
    exec(compile(raw,str(source),'exec'),module.__dict__)
    module.SCOPE=SCOPE;module.TARGETS=TARGETS
    pub=module.publisher();pub.locks=pub.ui_only_locks
    original_guards=pub.guards
    def guards(manifest,root,reader_stopped=False):
        original_guards(manifest,root,reader_stopped)
        subprocess.run(['systemctl','is-active','--quiet','marketing-worker.service'],check=True)
    def restart(manifest,fence=None):
        if manifest['scope']!=SCOPE:raise ValueError('webpush scope only')
        files=[v for k,v in TARGETS.items() if k.endswith('.py') and Path(v).exists()]
        subprocess.run(['/opt/python39/bin/python3.9','-m','py_compile']+files,check=True)
        subprocess.run(['systemctl','restart','marketing-worker.service'],check=True)
        subprocess.run(['systemctl','is-active','--quiet','marketing-worker.service'],check=True)
    pub.guards=guards;pub.restart_for=restart
    return pub

if __name__=='__main__':
    pub=publisher();raw=(HERE/'manifest.json').read_bytes();manifest=json.loads(raw)
    if sys.argv[1]=='inspect':result=pub.inspect(manifest,HERE)
    elif sys.argv[1]=='apply':result=pub.apply(manifest,HERE,sys.argv[2],raw,sys.argv[3])
    elif sys.argv[1]=='rollback':result=pub.rollback(Path(sys.argv[2]),sys.argv[3])
    else:raise ValueError('unknown action')
    print(json.dumps(result))
