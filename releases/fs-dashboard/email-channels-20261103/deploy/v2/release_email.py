"""Scoped adapter for the existing frozen publisher; retains locks/CAS/journal/rollback."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

HERE = Path(__file__).resolve().parent
BASE = Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
SCOPE = 'email-channels-20261103-v2'
TARGETS = {'market_worker.py':'/opt/marketing-worker/market_worker.py',
           'email_channels.py':'/opt/marketing-worker/email_channels.py',
           'marketing.html':'/opt/marketing-worker/web/marketing.html',
           'iggm-web.conf':'/etc/nginx/conf.d/iggm-web.conf'}

def publisher():
    source = BASE / 'release_source_tabs.py'
    module = types.ModuleType('email_existing_publisher')
    module.__file__ = str(source)
    exec(compile(source.read_bytes(),str(source),'exec'),module.__dict__)
    module.SCOPE = SCOPE
    module.TARGETS = TARGETS
    pub = module.publisher()
    pub.locks = pub.ui_only_locks
    original_guards = pub.guards
    def guards(manifest,root,reader_stopped=False):
        original_guards(manifest,root,reader_stopped)
        subprocess.run(['systemctl','is-active','--quiet','marketing-worker.service'],check=True)
    def restart(manifest,fence=None):
        if manifest['scope'] != SCOPE:
            raise ValueError('email scope only')
        subprocess.run(['nginx','-t'],check=True)
        sources=[TARGETS['market_worker.py']]
        if Path(TARGETS['email_channels.py']).exists():
            sources.append(TARGETS['email_channels.py'])
        subprocess.run(['/opt/python39/bin/python3.9','-m','py_compile']+sources,check=True)
        subprocess.run(['systemctl','restart','marketing-worker.service'],check=True)
        subprocess.run(['systemctl','reload','nginx.service'],check=True)
        subprocess.run(['systemctl','is-active','--quiet','marketing-worker.service'],check=True)
    pub.guards = guards
    pub.restart_for = restart
    return pub

if __name__ == '__main__':
    pub=publisher()
    raw=(HERE/'manifest.json').read_bytes()
    manifest=json.loads(raw)
    action=sys.argv[1]
    if action=='inspect': result=pub.inspect(manifest,HERE)
    elif action=='apply': result=pub.apply(manifest,HERE,sys.argv[2],raw,sys.argv[3])
    elif action=='rollback': result=pub.rollback(Path(sys.argv[2]),sys.argv[3])
    else: raise ValueError('unknown action')
    print(json.dumps(result))
