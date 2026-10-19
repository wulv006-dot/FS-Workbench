"""Existing UI-only publisher bridge: locks, CAS, backups, scoped rollback retained."""
import sys,json,hashlib
from pathlib import Path
P=Path(__file__).parent
BASE=Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
sys.path.insert(0,str(BASE))
import release_ui_finish as ui
ui.TARGETS=json.loads((P/'targets.json').read_text())
b=ui.publisher()
raw=(P/'manifest.json').read_bytes();m=json.loads(raw)
if sys.argv[1]=='inspect':print(json.dumps(b.inspect(m,P)))
elif sys.argv[1]=='apply':print(json.dumps(b.apply(m,P,sys.argv[2],raw,sys.argv[3])))
elif sys.argv[1]=='rollback':print(json.dumps(b.rollback(Path(sys.argv[2]),sys.argv[3])))
else:raise ValueError('unsupported action')
