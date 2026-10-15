$ErrorActionPreference='Stop'
$navigationRead=@'
python3 - <<'NAVIGATION_BASELINE'
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
paths=['/var/www/dashboard/fs-home/navigation.json','/var/lib/fs-navigation-formal-static/workspace-native-20261006-261bedcc395a/navigation.json',
       '/var/www/dashboard/fs-home/navigation.css','/var/www/dashboard/fs-home/hubnav.css',
       '/var/www/dashboard/modules/analytics/index.html','/var/www/dashboard/modules/sports/index.html',
       '/var/www/hub/hubnav.js','/var/www/dashboard/fs-home/brain/index.html',
       '/var/www/dashboard/fs-home/brain/brain.js','/var/www/dashboard/fs-home/brain/brain.css']
out={'observedAt':datetime.now(timezone.utc).isoformat(),'files':{},'productionWrites':0}
for path in paths:
 p=Path(path);b=p.read_bytes();s=p.stat()
 out['files'][path]={'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'uid':s.st_uid,'mode':s.st_mode&0o777}
 if path.endswith('/navigation.json'):
  x=json.loads(b);out['files'][path].update(sections=[r['id'] for r in x['sections']],toolIds=[r['id'] for r in x['tools']])
print(json.dumps(out))
NAVIGATION_BASELINE
'@
$result=& (Join-Path $PSScriptRoot '../../../../server_187/access/Invoke-Server187.ps1') -Action Run -RemoteCommand $navigationRead
if($LASTEXITCODE -ne 0){throw 'read-only navigation baseline failed'}
$result|Set-Content -LiteralPath (Join-Path $PSScriptRoot 'navigation-live-baseline.json') -Encoding utf8
