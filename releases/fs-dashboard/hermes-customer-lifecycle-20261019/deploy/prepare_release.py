from pathlib import Path
import hashlib,json,shutil,datetime,subprocess
from release_scope import TARGETS,SCOPE,APPLICATION_SCHEDULE
P=Path(__file__).parent
OLD=Path('/opt/fs-release-stage/hermes-report-repair-20261019-v6')
EXPECTED={'source/customer_tracking.py':'ff9bca8ae386caa565a679e035e7099389148e07fe9a397828661bb156d8ec33','source/tracking_controller.py':'602f34f28f17dc7c047e9afd4d2788114d527895763e734fc419560f09243f5f','source/tracking_tool.py':'f64794e31f092c6dd89f9b682472f9f8e45c1f169c788361d6d725f5921ecf8f','source/pool_reports.py':None,'source/page.js':'55cc9c2417dc09e1835243d26250cee2acad2aeb179dcdab49125e461048b02f','source/index.html':'6834d09bd80eda072f7bb32d1247e0b1ed274d935a823f0058284929a44f9b07'}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
base=OLD/'release_navigation_base.py'
assert sha(base)=='1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
shutil.copyfile(base,P/'release_navigation_base.py')
m=json.loads((OLD/'approved-manifest.json').read_text())
rows=[]
for n,t in TARGETS.items():
 if sha(Path(t))!=EXPECTED[n]:raise ValueError('baseline drift '+t)
 rows.append({'candidate':n,'target':t,'beforeSha256':EXPECTED[n],'sha256':sha(P/'candidate'/n),'mode':'0o644','owner':'0:0'})
# Fresh inventory: retain previous protected paths and former target paths, exclude only current exact scope.
paths={r['path'] for r in m['unchangedRequired']}|{r['target'] for r in m['files']}
guards=[{'path':t,'sha256':sha(Path(t))} for t in sorted(paths-set(TARGETS.values()))]
if any(r['sha256'] is None for r in guards):raise ValueError('protected baseline missing')
observed=datetime.datetime.now(datetime.timezone.utc).isoformat()
raw=json.dumps({'observed_at':observed,'files':rows,'protected':guards},sort_keys=True).encode();(P/'baseline.json').write_bytes(raw)
m.update(scope=SCOPE,sourceCommit='candidate-customer-pool-lifecycle-20261019',files=rows,unchangedRequired=guards,applicationScheduleChanges=APPLICATION_SCHEDULE,baselineObservedAt=observed,baselineSha256=hashlib.sha256(raw).hexdigest(),imageId=subprocess.check_output(['docker','inspect','-f','{{.Image}}','fc27-p2pah-session'],text=True).strip())
raw=json.dumps(m,indent=2).encode();(P/'approved-manifest.json').write_bytes(raw);print('MANIFEST',hashlib.sha256(raw).hexdigest(),'GUARDS',len(guards))
