"""Reuse the existing UI publisher locks, CAS, journal and scoped rollback."""
import json, sys
from pathlib import Path
P=Path(__file__).resolve().parent
sys.path.insert(0,'/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
import release_ui_finish as ui
ui.TARGETS=json.loads((P/'targets.json').read_text())
b=ui.publisher()
restart=b.restart_for
def activate(manifest,fence=None):
    restart(manifest,fence)
    import subprocess
    subprocess.run(['systemctl','restart','fs-campaign-dashboard.service'],check=True)
    subprocess.run(['systemctl','is-active','--quiet','fs-campaign-dashboard.service'],check=True)
b.restart_for=activate
raw=(P/'manifest.json').read_bytes();manifest=json.loads(raw)
if sys.argv[1]=='inspect':result=b.inspect(manifest,P)
elif sys.argv[1]=='apply':result=b.apply(manifest,P,sys.argv[2],raw,sys.argv[3])
elif sys.argv[1]=='rollback':result=b.rollback(Path(sys.argv[2]),sys.argv[3])
else:raise ValueError('unsupported action')
print(json.dumps(result))
