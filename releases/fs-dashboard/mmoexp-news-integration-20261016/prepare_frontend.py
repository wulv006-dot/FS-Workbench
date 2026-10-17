"""Prepare the existing immutable publisher on-host; never export active HTML/config."""
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent
PRIOR = Path('/opt/fs-business-refresh-20261015-ba0a83afd594/frontend')
OLD = 'workspace-native-20261006-ba0a83afd594'
ORIGINAL_GAME = '/var/lib/fs-navigation-formal-static/workspace-native-20261006-556cbd6567b0/game-monitor/index.html'
FRAGMENT = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'


def sha(value):
    return hashlib.sha256(value).hexdigest()


def main():
    spec = json.loads((ROOT/'baseline.json').read_text())
    for path, expected in {**spec['protected'], **spec['files']}.items():
        assert sha(Path(path).read_bytes()) == expected, 'live drift: '+path
    for name, expected in spec['assets'].items():
        assert sha((Path('/var/lib/fs-navigation-formal-static')/OLD/name).read_bytes()) == expected, name
    expected_publishers = {'release_workspace.py': 'e33b0bea76ec354b74249c608a628aa7a2b557934bfc9d406267ac78cdedc87c',
                           'release_navigation.py': 'c61ae129feccd8f81a63f51dde414753b620ee8658061a477b0997ae0befc89f'}
    for name, expected in expected_publishers.items():
        assert sha((PRIOR/name).read_bytes()) == expected, name
    original = Path(ORIGINAL_GAME).read_bytes()
    assert sha(original) == 'd7b85dba6e41049f65b04095819c517e2da00d615b51838297f31f06964938aa'
    changed = (ROOT/'daily.js').read_bytes()
    assert sha(changed) == spec['new_daily_sha256']
    manifest = json.loads((PRIOR/'release-manifest.json').read_text())
    assert set(spec['assets']) == {r['candidate'][7:] for r in manifest['immutableAssets']}
    identities = dict(spec['assets']);identities['game-monitor/index.html'] = sha(original);identities['game-monitor/daily.js'] = sha(changed)
    version = 'workspace-native-20261006-'+sha(json.dumps(identities, sort_keys=True).encode())[:12]
    stage = ROOT/'candidate'
    stage.mkdir()
    assets = stage/'assets'
    shutil.copytree(Path('/var/lib/fs-navigation-formal-static')/OLD, assets)
    (assets/'game-monitor/index.html').write_bytes(original)
    (assets/'game-monitor/daily.js').write_bytes(changed)
    conf = Path(FRAGMENT).read_text()
    assert Path(FRAGMENT).read_bytes() == conf.encode(), 'preserve config line endings'
    block = re.compile(r'^location = (\S+) \{\n.*?^\}', re.M|re.S)
    pages = {m[1]:m[0] for m in block.finditer(conf)}
    daily = pages['/dashboard/game-monitor/daily.js']
    old_alias = spec['routes']['/dashboard/game-monitor/daily.js']['alias'][0]
    assert old_alias in daily
    new_alias = '/var/lib/fs-navigation-formal-static/'+version+'/game-monitor/daily.js'
    altered = conf.replace(daily,daily.replace(old_alias,new_alias),1)
    copies = [m[0].replace(OLD,version) for m in block.finditer(conf) if m[1].startswith('/dashboard/workspace-assets/'+OLD+'/')]
    assert len(copies) == len(identities)
    news_routes = []
    for filename in ('seo-news.json','seo-news.status.json'):
        assert '/dashboard/game-monitor/'+filename not in pages
        route = pages['/dashboard/game-monitor/daily.json'].replace('/dashboard/game-monitor/daily.json','/dashboard/game-monitor/'+filename).replace('/var/lib/fs-boss-workspaces/public/game-monitor.json','/var/lib/fs-boss-workspaces/public/'+filename)
        assert 'auth_request /__nav_formal_native_session;' in route
        news_routes.append(route)
    addition = '\n\n# Shared MMOEXP SEO news, 2026-10-16.\n'+'\n\n'.join(copies+news_routes)+'\n'
    altered += addition
    locations = re.findall(r'^location = (\S+)', altered, re.M)
    assert len(locations) == len(set(locations))
    assert altered[:-len(addition)].replace(new_alias,old_alias) == conf
    for row in manifest['targets']:
        raw = Path(row['target']).read_bytes()
        candidate = altered.encode() if row['target'] == FRAGMENT else raw
        p = stage/row['candidate'];p.parent.mkdir(parents=True, exist_ok=True);p.write_bytes(candidate)
        row.update(beforeSha256=sha(raw), sha256=sha(candidate))
    protected = dict(spec['protected'])
    protected.update({str(Path('/var/lib/fs-navigation-formal-static')/OLD/name): value for name, value in spec['assets'].items()})
    for path in spec['files']:
        protected.pop(path, None)
    manifest.update(scope='Read shared MMOEXP SEO news separately from official announcements', releaseId=version,
                    releaseReady=False, requiredBusinessLedger=spec['businessLedger'],
                    unchangedRequired=[dict(path=p, sha256=h) for p,h in sorted(protected.items())],
                    immutableAssets=[dict(candidate='assets/'+n, target='/var/lib/fs-navigation-formal-static/'+version+'/'+n,
                                          url='/dashboard/workspace-assets/'+version+'/'+n, beforeSha256=None,
                                          sha256=sha((assets/n).read_bytes())) for n in sorted(identities)])
    contract = (json.dumps(manifest, indent=2)+'\n').encode()
    (stage/'release-contract.json').write_bytes(contract)
    manifest['releaseReady'] = True
    approved = (json.dumps(manifest, indent=2)+'\n').encode()
    (stage/'release-manifest.json').write_bytes(approved)
    publisher = (PRIOR/'release_workspace.py').read_text()
    assert (PRIOR/'release_workspace.py').read_bytes() == publisher.encode(), 'preserve publisher line endings'
    publisher, count = re.subn(r"CONTRACT_SHA = '[a-f0-9]+'", "CONTRACT_SHA = '"+sha(contract)+"'", publisher)
    assert count == 1
    (stage/'release_workspace.py').write_text(publisher)
    shutil.copyfile(PRIOR/'release_navigation.py', stage/'release_navigation.py')
    print(json.dumps({'stage':str(stage), 'releaseId':version, 'manifest_sha256':sha(approved),
                      'assets':len(identities), 'protected':len(protected), 'changed_asset':'game-monitor/daily.js'}))


if __name__ == '__main__':
    main()
