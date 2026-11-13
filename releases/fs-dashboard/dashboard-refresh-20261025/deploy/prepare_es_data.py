"""Stage the exact ES data batch using captured source files and target hashes."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

import es_data_release as release

BASE = '7042edaf90647cbd51ab7df3e35f7b4341f72b3f'
REPO = Path(__file__).resolve().parents[4]
ROOT = 'releases/fs-dashboard/'
DASH = ROOT + 'dashboard-refresh-20261025/source/'
DETAIL = ROOT + 'fc-detail-analytics-20261012/source/'
ES = ROOT + 'cache-archive-retention-20261025/source/'
USERS = ROOT + 'user-analytics-20261022/source/'
CHANNEL = ROOT + 'channel-effects-20261021/ui/'
EMAIL_ADAPTER = ROOT + 'order-email-export-20261111/publisher/adapter.py'
STATIC_OLD = {
    **{n:release.STATIC+'summary-performance-20261107-7309593bc091/'+n for n in release.UI[:3]},
    **{n:release.STATIC+'pmax-fc-scope-20261022-v1/'+n for n in release.UI[3:]},
}
LOCATIONS = {
    'business.js':'/dashboard/workspace-assets/workspace-native-20261006-8b7908ecad30/business.js',
    'home-business.js':'/dashboard/workspace-assets/workspace-native-20261006-72d7ba0dbca8/business.js',
    'legacy-business.js':'/dashboard/workspace-assets/workspace-native-20261006-fd4cfd0a70aa/business.js',
    **{n:'/dashboard/channel-effects/'+n for n in release.UI[3:]},
}
SOURCES = {
    **{'range/'+n:(DETAIL if n in ('fc_detail.py','fc_dashboard.py') else DASH)+n for n in release.RANGE_FILES},
    **{'host/'+n:(USERS if n=='user_store.py' else ES)+n for n in release.HOST_FILES},
    **{'ui/'+n:(DASH if n in release.UI[:3] else CHANNEL)+n for n in release.UI},
}
REVIEWED_CONFLICTS = {
    'range_api.py': (
        " HERMES.conversation=CONVERSATION\n HERMES.actual_profits=ACTUAL_PROFITS\n",
        ' from order_facts_api import OrderFactsService\n from order_facts_runtime import collect as collect_order_facts\n'
        ' ORDER_FACTS=OrderFactsService(CHANNELS,collect_order_facts,\n'
        '  games=[(str(row[3]),row[1]) for row in PROFILES if str(row[3]).isdigit() and int(row[3])>0])\n',
    ),
    'admin_summary.py': (
        'from management_profiles import PROFILES as MANAGEMENT_PROFILES\n'
        'GAMES.update({str(p[3]): "" for p in MANAGEMENT_PROFILES})\n\n'
        'def collect(request, game, start, end):\n',
        'def collect(request, game, start, end, *, country_code="", local_repeat=None):\n',
    ),
}
INDEX_BRANCH = ('            if self.config.get(\'revision_range_index\') is True and user_version_index.ready(db, current):\n'
    '                return sorted((self.analytics_row_v1(row) for row in user_version_index.read(db, target, start=start, end=end)\n'
    "                               if row['valid']), key=lambda row: (row['paid_at'], row['order_key']))\n")
REPLAY_RANGE = ('        if start is not None:\n'
    '            start, end = stamp(start).isoformat(), stamp(end).isoformat()\n'
    '            if not start < end:\n'
    "                raise ValueError('analytics_period_required')\n")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def compose(name, before, desired, live):
    if live == before or live.replace(b'\r\n',b'\n') == before:
        return desired
    with tempfile.TemporaryDirectory(prefix='admin-es-merge-') as folder:
        paths = [Path(folder) / n for n in ('candidate','base','live')]
        for path, raw in zip(paths,(desired,before,live.replace(b'\r\n',b'\n'))):
            path.write_bytes(raw)
        result = subprocess.run(['git','merge-file','-p','-L','candidate','-L','base','-L','live',*map(str,paths)],capture_output=True)
    if result.returncode == 0:
        return result.stdout
    text = result.stdout.decode('utf-8')
    conflict = re.compile(r'^<<<<<<< candidate\n(.*?)^=======\n(.*?)^>>>>>>> live\n',re.M|re.S)
    matches = list(conflict.finditer(text))
    if result.returncode != 1 or len(matches) != 1:
        raise ValueError('unresolved source drift: '+name)
    candidate, production = matches[0].groups()
    if name in REVIEWED_CONFLICTS and (production,candidate) == REVIEWED_CONFLICTS[name]:
        replacement = production+candidate if name=='range_api.py' else production.replace('def collect(request, game, start, end):\n',candidate)
    elif name=='user_store.py' and not production and b'import user_version_index' not in live:
        if (INDEX_BRANCH not in candidate or 'if target == current and start is not None:' not in candidate
                or 'if bounded_only:' not in candidate or text.count(REPLAY_RANGE) != 1):
            raise ValueError('unresolved user store bounded revision drift')
        replacement = candidate.replace(INDEX_BRANCH,'')
        # Live keeps range normalization below replay. Current SQL must use the same canonical timestamps.
        text = text.replace(REPLAY_RANGE,'',1)
        current = '        target = int(version)\n        result = {}\n'
        if text.count(current) != 1:
            raise ValueError('unresolved user store range validation drift')
        text = text.replace(current,'        target = int(version)\n'+REPLAY_RANGE+'        result = {}\n',1)
    else:
        raise ValueError('unresolved source drift: '+name)
    return conflict.sub(lambda _:replacement,text,count=1).encode('utf-8')


def route_payload(raw, version):
    for name, location in LOCATIONS.items():
        block = re.compile(rb'(?m)^location = '+re.escape(location.encode())+rb' \{\r?\n.*?^\}',re.S)
        matches = list(block.finditer(raw))
        old = ('alias '+STATIC_OLD[name]+';').encode()
        new = ('alias '+release.STATIC+version+'/'+name+';').encode()
        if len(matches)!=1 or matches[0].group().count(old)!=1:
            raise ValueError('unexpected ES route baseline: '+location)
        raw = block.sub(lambda match:match[0].replace(old,new,1),raw,count=1)
    return raw


def build(source, source_commit, before_hashes, captured, output, *, ready=False, frozen_base=None):
    captured, output = Path(captured), Path(output)
    if output.exists():
        raise FileExistsError('new ES stage required')
    assets = {}
    for name in release.UI:
        live = (captured/name).read_bytes()
        if digest(live)!=before_hashes[STATIC_OLD[name]]:
            raise ValueError('captured ES static hash differs: '+name)
        relative = SOURCES['ui/'+name]
        assets[name] = compose(name,source(BASE,relative),source(source_commit,relative),live)
    version = 'admin-es-20261113-' + digest(b''.join(n.encode()+b'\0'+assets[n] for n in release.UI))[:12]
    targets = release.targets(version)
    files, payloads = [], {}
    for name,target in targets.items():
        before = before_hashes[target] if name not in release.NEW else before_hashes.get(target)
        leaf = Path(name).name
        if name=='routes.conf':
            live = (captured/name).read_bytes()
            if digest(live)!=before:
                raise ValueError('captured formal route hash differs')
            raw = route_payload(live,version)
        else:
            raw = assets[leaf] if name.startswith('ui/') else source(source_commit,SOURCES[name])
            if not name.startswith('ui/') and before is not None:
                base = source(BASE,SOURCES[name])
                if digest(base)!=before:
                    live = (captured/leaf).read_bytes()
                    if digest(live)!=before:
                        raise ValueError('captured ES source hash differs: '+leaf)
                    raw = compose(leaf,base,raw,live)
        if leaf.endswith('.py'):
            ast.parse(raw,filename=leaf,feature_version=(3,9))
        files.append(dict(candidate=name,target=target,sha256=digest(raw),beforeSha256=before))
        payloads[name] = raw
    manifest = dict(schemaVersion=1,scope=release.SCOPE,releaseReady=ready,businessWrites=False,timersChanged=False,
        sourceCommit=source_commit,assetVersion=version,files=files,runtimeRequired=release.RUNTIME,
        unchangedRequired=[dict(path=n,sha256=before_hashes[n]) for n in sorted(release.PROTECTED)])
    release.contract(manifest)
    output.mkdir(parents=True)
    for name,raw in payloads.items():
        path = output/'candidate'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    (output/release.ADAPTER).write_bytes(source(source_commit,EMAIL_ADAPTER))
    (output/'es_data_release.py').write_bytes(Path(release.__file__).read_bytes())
    (output/'manifest.json').write_bytes((json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode())
    if frozen_base is not None:
        release.publisher(output,manifest,frozen_base=frozen_base).validate(manifest,output)
    return manifest


def git_source(ref,relative):
    return subprocess.check_output(['git','show',ref+':'+relative],cwd=REPO)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-commit',required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--captured',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frozen-base',type=Path,required=True)
    parser.add_argument('--release-ready',action='store_true')
    args=parser.parse_args()
    manifest=build(git_source,args.source_commit,json.loads(args.baseline.read_text('utf-8-sig')),args.captured,args.output,
                   ready=args.release_ready,frozen_base=args.frozen_base)
    print(json.dumps({'files':len(manifest['files']),'assetVersion':manifest['assetVersion'],
                      'manifestSha256':digest((args.output/'manifest.json').read_bytes())}))
