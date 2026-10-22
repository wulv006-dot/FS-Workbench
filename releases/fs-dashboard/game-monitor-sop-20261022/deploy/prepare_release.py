"""Prepare a content-only derivative with the existing immutable workspace publisher."""
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil

TASK = Path('/var/lib/fs-hermes-fc/profile/game-monitor-sop-20261022')
PRIOR = Path('/var/lib/fs-navigation-staging/news-weekly-unified-20261016/frontend/candidate')
STAGE = Path('/var/lib/fs-navigation-staging/game-monitor-sop-20261022/candidate-final')
OLD = 'workspace-native-20261006-c247af54280f'
STATIC = Path('/var/lib/fs-navigation-formal-static')
FRAGMENT = Path('/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf')
LEDGER = Path('/var/lib/fs-dashboard-release/current.json')
sha = lambda raw: hashlib.sha256(raw).hexdigest()


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def main():
    assert not STAGE.exists(), 'Inspect original stage before retry'
    manifest = json.loads((PRIOR/'release-manifest.json').read_bytes())
    assert manifest['releaseId'] == OLD
    publisher = (PRIOR/'release_workspace.py').read_bytes()
    normalized, count = re.subn(rb"CONTRACT_SHA = '[a-f0-9]+'", b"CONTRACT_SHA = 'FROZEN'", publisher)
    assert count == 1 and sha(normalized) == '152bf689ef5ba5a25bc64be27da517ec042a1a10f1f98cf959550da53d5cb4cd'
    assert sha((PRIOR/'release_navigation.py').read_bytes()) == 'c61ae129feccd8f81a63f51dde414753b620ee8658061a477b0997ae0befc89f'
    baseline = json.loads((TASK/'baseline.json').read_text())
    html = next(row for row in baseline['entries'] if row['name'] == 'index.html')
    assert sha(Path(html['live']).read_bytes()) == html['sha256']
    conf_raw = FRAGMENT.read_bytes()
    conf = conf_raw.decode()
    names = {row['candidate'][7:] for row in manifest['immutableAssets']}
    assert len(names) == 139
    assert names == {p.relative_to(STATIC/OLD).as_posix() for p in (STATIC/OLD).rglob('*') if p.is_file()}
    identities = {name: sha((STATIC/OLD/name).read_bytes()) for name in names}
    changes = {'game-monitor/index.html': (TASK/'candidate/index.html').read_bytes()}
    validation = json.loads((TASK/'VALIDATION.json').read_bytes())
    assert sha(changes['game-monitor/index.html']) == validation['baseline']['candidate_index_sha256']
    assert sha(changes['game-monitor/index.html']) != html['sha256']
    for path in (TASK/'candidate/assets').rglob('*'):
        if path.is_file():
            assert not path.is_symlink()
            relative = path.relative_to(TASK/'candidate').as_posix()
            assert re.fullmatch(r'assets/[a-zA-Z0-9_/-]+\.(?:jpg|jpeg|png|webp)', relative)
            assert 'maple' in relative.lower(), 'MapleStory assets only'
            changes['game-monitor/'+relative] = path.read_bytes()
    identities.update({name: sha(raw) for name, raw in changes.items()})
    version = 'workspace-native-20261006-' + sha(json.dumps(identities, sort_keys=True).encode())[:12]
    blocks = list(re.finditer(r'^location = (\S+) \{\n.*?^\}', conf, re.M | re.S))
    roots = {m[1]: m[0] for m in blocks}
    changed = conf
    for name in changes:
        route = '/dashboard/'+name
        if route in roots:
            block = roots[route]
            alias = re.findall(r'^\s*alias ([^;]+);', block, re.M)
            assert len(alias) == 1
            changed = replace_once(changed, block, replace_once(block, alias[0], str(STATIC/version/name)))
    copies = [m[0].replace(OLD, version) for m in blocks if m[1].startswith('/dashboard/workspace-assets/'+OLD+'/')]
    assert len(copies) == 139
    template_name = 'game-monitor/assets/covers/maplestory.jpg'
    root_template = roots['/dashboard/'+template_name]
    asset_template = roots['/dashboard/workspace-assets/'+OLD+'/'+template_name]
    for name in sorted(set(identities)-names):
        root_block = root_template.replace('/dashboard/'+template_name, '/dashboard/'+name)
        old_alias = re.findall(r'^\s*alias ([^;]+);', root_template, re.M)[0]
        copies.append(replace_once(root_block, old_alias, str(STATIC/version/name)))
        copies.append(asset_template.replace(OLD, version).replace(template_name, name))
    changed += '\n\n# Hermes MapleStory content SOP, 2026-10-22.\n' + '\n\n'.join(copies) + '\n'
    locations = re.findall(r'^location = (\S+)', changed, re.M)
    assert len(locations) == len(set(locations)), 'Duplicate route'
    target_names = {row['target'] for row in manifest['targets']}
    protected_names = {row['path'] for row in manifest['unchangedRequired']} | {str(STATIC/OLD/name) for name in names}
    protected = {name: sha(Path(name).read_bytes()) for name in protected_names-target_names}
    ledger = json.loads(LEDGER.read_bytes())
    STAGE.mkdir(parents=True)
    shutil.copytree(STATIC/OLD, STAGE/'assets')
    for name, raw in changes.items():
        destination = STAGE/'assets'/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    for row in manifest['targets']:
        before = Path(row['target']).read_bytes()
        after = changed.encode() if row['target'] == str(FRAGMENT) else before
        destination = STAGE/row['candidate']
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(after)
        row.update(beforeSha256=sha(before), sha256=sha(after))
    assert FRAGMENT.read_bytes() == conf_raw
    manifest.update(scope='Hermes MapleStory ten-column content standard; existing schedules preserved', releaseId=version,
                    releaseReady=False, requiredBusinessLedger=ledger,
                    unchangedRequired=[dict(path=name, sha256=h) for name, h in sorted(protected.items())],
                    immutableAssets=[dict(candidate='assets/'+name, target=str(STATIC/version/name),
                                          url='/dashboard/workspace-assets/'+version+'/'+name,
                                          beforeSha256=None, sha256=h) for name, h in sorted(identities.items())])
    contract = (json.dumps(manifest, indent=2)+'\n').encode()
    (STAGE/'release-contract.json').write_bytes(contract)
    manifest['releaseReady'] = True
    approved = (json.dumps(manifest, indent=2)+'\n').encode()
    (STAGE/'release-manifest.json').write_bytes(approved)
    source = publisher.decode()
    source, count = re.subn(r'^NAMES = .*$', 'NAMES = {'+', '.join(repr(n) for n in sorted(identities))+'}', source, flags=re.M)
    assert count == 1
    source, count = re.subn(r"CONTRACT_SHA = '[a-f0-9]+'", "CONTRACT_SHA = '"+sha(contract)+"'", source)
    assert count == 1
    ast.parse(source)
    (STAGE/'release_workspace.py').write_text(source)
    shutil.copyfile(PRIOR/'release_navigation.py', STAGE/'release_navigation.py')
    for name, expected in protected.items():
        assert sha(Path(name).read_bytes()) == expected, name
    result = dict(stage=str(STAGE), releaseId=version, manifest_sha256=sha(approved),
                  assets=len(identities), changed_assets={name: sha(raw) for name, raw in changes.items()}, protected=len(protected))
    (STAGE.parent/'prepared-final.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
