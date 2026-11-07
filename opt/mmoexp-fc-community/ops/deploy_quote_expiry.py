"""Single-file quote-session UX release; leave config and publication records intact."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0,'/opt/mmoexp-fc-news-stage-20261108-core')
from deploy_news_center import atomic, run

if len(sys.argv)!=2:
    raise SystemExit('Provide reviewed candidate SHA256')
base=Path('/opt/mmoexp-fc-community')
target=base/'quote_panel.py'
source=Path('/tmp/fc27-quote-expiry-20261108/quote_panel.py')
expected='00246d672782bd5207a14f3a70a22449006a119159226acec67b7c3ed2d79d00'
original=target.read_bytes()
candidate=source.read_bytes()
if hashlib.sha256(original).hexdigest()!=expected or hashlib.sha256(candidate).hexdigest()!=sys.argv[1]:
    raise SystemExit('Quote source drift')
config=(base/'content.config.json').read_bytes()
markers={p:p.read_bytes() for p in (base/'var').glob('*panel*.json')}
backup=base/'backups'/('quote-expiry-'+str(int(time.time())))
backup.mkdir(mode=0o700)
shutil.copy2(target,backup/'quote_panel.py')
try:
    run('systemctl','stop','mmoexp-fc-community')
    atomic(target,candidate)
    run('systemctl','start','mmoexp-fc-community')
    for _ in range(40):
        pid=int(run('systemctl','show','mmoexp-fc-community','-p','MainPID').split('=')[1])
        ready=json.loads((base/'var/ready.json').read_text())
        if ready.get('connected') and ready.get('pid')==pid and ready.get('test_guild_present'): break
        time.sleep(1)
    else: raise RuntimeError('Bot not ready')
    if (base/'content.config.json').read_bytes()!=config or any(p.read_bytes()!=data for p,data in markers.items()):
        raise RuntimeError('Unexpected config or marker change')
except Exception:
    run('systemctl','stop','mmoexp-fc-community'); atomic(target,original)
    run('systemctl','start','mmoexp-fc-community')
    raise
result={'status':'ready','backup':str(backup),'pid':pid,'sha256':sys.argv[1],'config_markers_unchanged':True}
Path('/tmp/fc27-quote-expiry-20261108/deployment.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
