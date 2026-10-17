"""Freeze daily source/units using the existing scoped navigation publisher."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil

ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent / 'fc_daily_20261013/release/deploy/release_navigation.py'
if not BASE.exists():
    BASE = ROOT.parent / 'fc-daily-20261013/deploy/release_navigation.py'
SCOPE = 'fs-boss-daily-20261013'
UPDATE_SCOPE = 'fs-boss-daily-update-20261013'
TARGETS = {
    **{'boss/' + n: '/opt/fs-boss-workspaces/backend/' + n
       for n in ('boss_daily.py', 'game_intelligence.py', 'management_daily.py')},
    'boss/targets.json': '/opt/fs-boss-workspaces/source/management/targets.json',
    **{'units/' + n: '/etc/systemd/system/' + n
       for n in ('fs-boss-game-monitor.service', 'fs-boss-game-monitor.timer',
                 'fs-boss-management.service', 'fs-boss-management.timer')},
}


def replace(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after, 1)


def previous_manifest(path):
    raw = Path(path).read_bytes()
    manifest = json.loads(raw)
    rows = manifest.get('files', [])
    if (manifest.get('schemaVersion') != 1 or manifest.get('scope') not in (SCOPE, UPDATE_SCOPE)
            or manifest.get('releaseReady') is not True or not isinstance(rows, list)
            or len(rows) != len(TARGETS) or any(not isinstance(row, dict) for row in rows)
            or {row.get('candidate') for row in rows} != set(TARGETS)):
        raise ValueError('previous approved manifest must contain exact boss scope')
    for row in rows:
        if row.get('target') != TARGETS[row['candidate']] or not isinstance(row.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', row['sha256']):
            raise ValueError('previous approved target or SHA invalid')
    return raw, {row['candidate']: row['sha256'] for row in rows}


def build(update_from=None):
    previous, before = previous_manifest(update_from) if update_from is not None else (None, {})
    scope = UPDATE_SCOPE if previous is not None else SCOPE
    out = ROOT / ('backend-update-release' if previous is not None else 'backend-release')
    if previous is not None:
        out.mkdir(parents=True, exist_ok=True)
        evidence = out / ('previous-manifest.' + hashlib.sha256(previous).hexdigest() + '.json')
        if evidence.exists():
            if evidence.read_bytes() != previous:
                raise ValueError('previous manifest evidence changed')
        else:
            with evidence.open('xb') as handle:
                handle.write(previous)
    rows = []
    for name, target in TARGETS.items():
        leaf = name.split('/')[-1]
        source = (ROOT / 'deploy' / leaf if name.startswith('units/') else
                  ROOT / 'source/management/targets.json' if leaf == 'targets.json' else ROOT / 'backend' / leaf)
        destination = out / 'candidate' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        rows.append(dict(candidate=name, target=target, beforeSha256=before.get(name),
                         sha256=hashlib.sha256(destination.read_bytes()).hexdigest()))
    live = json.loads((ROOT / 'baseline/live.json').read_text('utf-8'))
    dependencies = json.loads((ROOT / 'coordination/backend-dependency.json').read_text('utf-8'))
    scheduler = json.loads((ROOT / 'baseline/scheduler.json').read_text('utf-8'))
    assert scheduler['timezone'] == 'Asia/Shanghai' and scheduler['systemd_version'] == 219
    protected = {r['path']: r for r in dependencies}
    shared_model = '/opt/fs-exact-range-20261001/fc_daily_model.py'
    protected[shared_model] = dict(path=shared_model, sha256=live['files'][shared_model]['sha256'])
    protected['/etc/localtime'] = dict(path='/etc/localtime', sha256=scheduler['localtime_sha256'])
    protected.update({p: dict(path=p, sha256=v) for p, v in live['protected_hashes'].items()})
    manifest = dict(schemaVersion=1, scope=scope, releaseReady=False, files=rows,
                    unchangedRequired=list(protected.values()),
                    runtimeRequired={'fs-business-range.service': {'ActiveState': 'active'}})
    (out / 'approved-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', 'utf-8')
    code = BASE.read_text('utf-8')
    code = replace(code, "DAILY_SCOPE='fc-daily-20261013'", "BOSS_SCOPE="+repr(SCOPE)+"\nBOSS_UPDATE_SCOPE="+repr(UPDATE_SCOPE)+"\nBOSS_TARGETS="+repr(TARGETS)+"\nDAILY_SCOPE='fc-daily-20261013'")
    code = replace(code, 'def expected_files(manifest):', 'def expected_files(manifest):\n if manifest.get("scope") in (BOSS_SCOPE,BOSS_UPDATE_SCOPE):return set(BOSS_TARGETS)')
    code = replace(code, 'def target_for(rel):', 'def target_for(rel):\n if rel in BOSS_TARGETS:return BOSS_TARGETS[rel]')
    code = replace(code, " protected={x['path']:x['sha256'] for x in manifest['unchangedRequired']}",
                   " if manifest.get('scope')==BOSS_SCOPE and any(r.get('beforeSha256') is not None for r in files):raise ValueError('first boss release requires absent targets')\n if manifest.get('scope')==BOSS_UPDATE_SCOPE and any(not isinstance(r.get('beforeSha256'),str) or not HASH.fullmatch(r['beforeSha256']) for r in files):raise ValueError('boss update requires existing target SHA')\n protected={x['path']:x['sha256'] for x in manifest['unchangedRequired']}")
    code = replace(code, " if manifest.get('scope')==DAILY_SCOPE:\n  for target in DAILY_TARGETS.values():",
                   " if manifest.get('scope') in (DAILY_SCOPE,BOSS_SCOPE,BOSS_UPDATE_SCOPE):\n  for target in (DAILY_TARGETS if manifest['scope']==DAILY_SCOPE else BOSS_TARGETS).values():")
    code = replace(code, 'def restart_for(manifest):', '''def restart_for(manifest):
 if manifest.get('scope') in (BOSS_SCOPE,BOSS_UPDATE_SCOPE):
  # Installation does not start tasks; enable the two timers after first-run acceptance.
  subprocess.run(['systemctl','daemon-reload'],check=True)
  return''')
    # Only activation dispatch gains this scope; it does not take the unrelated collector lock.
    code = code.replace('(QUERY_SCOPE,TRAFFIC_SCOPE,LIVE_SCOPE,CACHE_FIX_SCOPE,GAMES_SCOPE,DEMAND_SCOPE,BOUNDARY_SCOPE,DETAIL_SCOPE,DAILY_SCOPE):restart_for(manifest)',
                        '(QUERY_SCOPE,TRAFFIC_SCOPE,LIVE_SCOPE,CACHE_FIX_SCOPE,GAMES_SCOPE,DEMAND_SCOPE,BOUNDARY_SCOPE,DETAIL_SCOPE,DAILY_SCOPE,BOSS_SCOPE,BOSS_UPDATE_SCOPE):restart_for(manifest)')
    (out / 'release_navigation.py').write_bytes(code.encode('utf-8'))
    print(json.dumps(dict(scope=scope, files=len(rows), releaseReady=False,
                          manifestSha256=hashlib.sha256((out/'approved-manifest.json').read_bytes()).hexdigest())))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--update-from', type=Path, help='Exact previous approved eight-file manifest; output uses backend-update-release.')
    build(parser.parse_args().update_from)
