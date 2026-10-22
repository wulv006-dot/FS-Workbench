"""Build the exact reviewed module stage from a current source checkout and live SHA receipt."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from patch_navigation import patch
from release import BASE_SHA, NEW, REPOSITORY_SOURCES, SCOPE, TARGETS

HERE=Path(__file__).resolve().parent


def prepare(checkout, baseline, navigation, destination):
    if destination.exists():
        raise ValueError('new_stage_required')
    before={r['path']:r['sha256'] for r in baseline['targets']}
    if set(before)!=set(TARGETS.values()) or any((before[v] is None)!=(k in NEW) for k,v in TARGETS.items()):
        raise ValueError('exact_live_baseline_required')
    protected=baseline['protected']
    if any(not r['sha256'] for r in protected) or set(before)&{r['path'] for r in protected}:
        raise ValueError('protected_boundary')
    base=checkout/'fs_channel_dashboard_20261021/deploy/release_navigation_base.py'
    if hashlib.sha256(base.read_bytes()).hexdigest()!=BASE_SHA:
        raise ValueError('frozen_publisher_drift')
    nav=patch({name:(navigation/name).read_bytes() for name in ('navigation.json','hubnav.js','navigation.conf')})
    module=checkout/'releases/fs-dashboard/user-analytics-20261022'
    rows=[]
    payload={}
    for relative,target in TARGETS.items():
        if relative.startswith('nav/'):
            raw=nav[relative.split('/')[1]]
        else:
            source=REPOSITORY_SOURCES[relative]
            source=(module/source) if relative.startswith(('runtime/','ui/','units/')) else checkout/source
            raw=source.read_bytes()
        payload[relative]=raw
        rows.append(dict(candidate=relative,target=target,sha256=hashlib.sha256(raw).hexdigest(),beforeSha256=before[target],owner='0:0',mode='0o644'))
    destination.mkdir(parents=True)
    for relative,raw in payload.items():
        path=destination/'candidate'/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    shutil.copy2(HERE/'release.py',destination/'release.py')
    shutil.copy2(base,destination/'release_navigation_base.py')
    value=dict(schemaVersion=1,releaseReady=False,scope=SCOPE,businessWrites=False,timersChanged=True,
               imageId='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544',
               runtimeRequired={name:{'ActiveState':'active'} for name in ('fs-business-range.service','fs-hermes-fc.service','fs-hermes-desktop.service','auth-portal.service')},
               files=rows,unchangedRequired=protected)
    (destination/'approved-manifest.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    return value


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--checkout',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--navigation',type=Path,required=True);p.add_argument('--destination',type=Path,required=True);a=p.parse_args()
    result=prepare(a.checkout,json.loads(a.baseline.read_text('utf-8')),a.navigation,a.destination)
    print(json.dumps(dict(releaseReady=False,files=len(result['files']),protected=len(result['unchangedRequired']))))
