"""Controlled local preview: synthetic fixtures only, no production requests."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit, parse_qs

MODULE = Path(__file__).resolve().parents[1]
REPO = MODULE.parents[2]
BASE = '5229a46a36a08e974bda3d8a7567c5d5a2790639'
STAGE = REPO / '.agent_runtime/fc-current-risks-preview'
FRAGMENT = 'releases/fs-dashboard/fc-detail-analytics-20261012/frontend/fc-detail.js'


def build():
    old = subprocess.run(['git', '-C', str(REPO), 'show', BASE+':'+FRAGMENT],
                         check=True, capture_output=True).stdout
    original = (MODULE/'frontend/assets/business.js').read_bytes()
    if original.count(old) != 1: raise ValueError('base_fragment_mismatch')
    new = (MODULE/'frontend/fc-detail.js').read_bytes()
    before, after = original.split(old)
    shutil.copytree(MODULE/'frontend/assets', STAGE/'frontend/assets', dirs_exist_ok=True)
    artifact = before + new + after
    (STAGE/'frontend/assets/business.js').write_bytes(artifact)
    receipt = {'base_commit':BASE, 'base_asset_sha256':sha256(original).hexdigest(),
               'base_fragment_sha256':sha256(old).hexdigest(), 'new_fragment_sha256':sha256(new).hexdigest(),
               'artifact_sha256':sha256(artifact).hexdigest(), 'prefix_sha256':sha256(before).hexdigest(),
               'suffix_sha256':sha256(after).hexdigest(), 'other_assets_unchanged':True,
               'production_ready':False, 'synthetic_preview':True}
    for p in (MODULE/'frontend/assets').iterdir():
        if p.name != 'business.js' and p.is_file():
            if p.read_bytes() != (STAGE/'frontend/assets'/p.name).read_bytes():raise ValueError('protected_asset_changed')
    (STAGE/'build-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    return receipt


def serve():
    spec=importlib.util.spec_from_file_location('fc_existing_preview',MODULE/'preview.py')
    preview=importlib.util.module_from_spec(spec);spec.loader.exec_module(preview)
    sys.path.insert(0,str(MODULE/'tests'))
    from test_fc_detail import row, data
    state={'scenario':'full','version':1,'as_of':datetime.now(timezone.utc).replace(microsecond=0)}
    def dataset():
        at=state['as_of'].astimezone(timezone(timedelta(hours=8)))
        def stamp(hours):return (at-timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
        paid=[row(n,'20.00',paytime=stamp(30)) for n in range(1,13)]
        pool=[row(100+n,'300.00' if n%2 else '40.00',status=91 if n%3==0 else 31,
                  status_format='问题单' if n%3==0 else '发货·发货中',paytime=stamp(12 if n<4 else 48 if n<9 else 96)) for n in range(1,13)]
        if state['version']>1:pool.append(row(150,'400.00',status=91,status_format='问题单',paytime=stamp(48)))
        if state['scenario']=='missing':
            pool[2]['amount_cents']=None
            pool[3]['paid_at']=None;pool[3]['created_at']=None
            pool[4]['paid_at']=None;pool[4]['created_at']=(at-timedelta(hours=50)).isoformat()
        result=data(paid,pool);result['as_of']=state['as_of'].isoformat()
        result['snapshot_id']='fc-detail-preview-%s-%s'%(state['scenario'],state['version'])
        result['coverage']['backlog_status']='partial' if state['scenario']=='incomplete' else 'available'
        result['coverage']['paid_complete']=True;result['coverage']['missing_days']=[]
        return result
    preview.ROOT=STAGE
    preview.dataset=dataset
    class Handler(preview.Handler):
        def do_GET(self):
            u=urlsplit(self.path)
            if u.path=='/__fixture':
                args=parse_qs(u.query);scenario=args.get('scenario',['full'])[0]
                if scenario not in ('full','missing','incomplete'):return self.reply({'error':'invalid_fixture'},400)
                state['scenario']=scenario;state['version']+=1;state['as_of']=datetime.now(timezone.utc).replace(microsecond=0)
                return self.reply({'synthetic':True,**{k:state[k] for k in ('scenario','version')}})
            return super().do_GET()
    print('Synthetic FC preview http://127.0.0.1:8844/dashboard/analytics/?mode=business&b_profile=FC27&b_group=sports&b_range=30',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8844),Handler).serve_forever()


if __name__=='__main__':
    print(json.dumps(build()),flush=True)
    if '--serve' in sys.argv:serve()
