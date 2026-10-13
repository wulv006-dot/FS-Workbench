"""Single shared adapter update using the Advisor's existing guarded publisher."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
BASE = Path('D:/codex/2026-10-13/task/advisor/activation/deploy/release_navigation.py')
if not BASE.exists():
    BASE = ROOT.parent / 'ai-advisor-20261013/activation/deploy/release_navigation.py'
SCOPE = 'fs-boss-insights-null-date-20261013'
CANDIDATE = 'advisor/boss_insights.py'
TARGET = '/opt/fs-exact-range-20261001/boss_insights.py'
BEFORE = '0bc0ca3ccdc536a036cd22a7df9afb311bb37cd1bba5b4e7f30b7a20c99fadd6'
SHARED = {'/opt/fs-exact-range-20261001/' + name for name in
          ('range_api.py', 'fc_daily.py', 'ai_advisor.py', 'ai_advisor_model.py')}


def replace(code, before, after):
    if code.count(before) != 1:
        raise ValueError('publisher source shape changed')
    return code.replace(before, after, 1)


def build(dependencies=None):
    deps = json.loads(Path(dependencies or ROOT / 'coordination/backend-dependency.json').read_text('utf-8'))
    if (not isinstance(deps, list) or len(deps) != 5 or any(not isinstance(row, dict) for row in deps)
            or {row.get('path') for row in deps} != SHARED | {TARGET}
            or any(not isinstance(row.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', row['sha256']) for row in deps)):
        raise ValueError('exact shared dependency hashes required')
    hashes = {row['path']: row['sha256'] for row in deps}
    if hashes[TARGET] != BEFORE:
        raise ValueError('approved insights baseline differs')
    live = json.loads((ROOT / 'baseline/live.json').read_text('utf-8'))
    protected = dict(live['protected_hashes'])
    protected.update({path: hashes[path] for path in SHARED})
    model = '/opt/fs-exact-range-20261001/fc_daily_model.py'
    protected[model] = live['files'][model]['sha256']
    if TARGET in protected or any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value) for value in protected.values()):
        raise ValueError('invalid protected dependency hash')
    payload = (ROOT / 'backend/boss_insights.py').read_bytes()
    manifest = dict(schemaVersion=1, scope=SCOPE, releaseReady=False,
                    files=[dict(candidate=CANDIDATE, target=TARGET, beforeSha256=BEFORE,
                                sha256=hashlib.sha256(payload).hexdigest())],
                    unchangedRequired=[dict(path=path, sha256=value) for path, value in sorted(protected.items())],
                    runtimeRequired={'fs-business-range.service': {'ActiveState': 'active'}})
    code = BASE.read_text('utf-8')
    code = replace(code, "ADVISOR_SCOPE='fs-ai-advisor-20261013'",
                   'INSIGHTS_SCOPE=' + repr(SCOPE) + '\nINSIGHTS_BEFORE=' + repr(BEFORE) +
                   '\nINSIGHTS_PROTECTED=' + repr(sorted(SHARED)) + "\nADVISOR_SCOPE='fs-ai-advisor-20261013'")
    code = replace(code, 'def expected_files(manifest):',
                   'def expected_files(manifest):\n if manifest.get("scope")==INSIGHTS_SCOPE:return {"advisor/boss_insights.py"}')
    code = replace(code, " protected={x['path']:x['sha256'] for x in manifest['unchangedRequired']}",
                   " protected={x['path']:x['sha256'] for x in manifest['unchangedRequired']}\n"
                   " if manifest.get('scope')==INSIGHTS_SCOPE:\n"
                   "  if files[0].get('beforeSha256')!=INSIGHTS_BEFORE:raise ValueError('approved insights baseline differs')\n"
                   "  if any(not HASH.fullmatch(protected.get(p,'')) for p in INSIGHTS_PROTECTED):raise ValueError('shared consumers must be protected')\n"
                   "  if '/opt/fs-exact-range-20261001/boss_insights.py' in protected:raise ValueError('target cannot be protected')\n"
                   "  if manifest.get('runtimeRequired',{}).get('fs-business-range.service')!={'ActiveState':'active'}:raise ValueError('existing active range required')")
    code = replace(code, " if manifest.get('scope') in (DAILY_SCOPE,ADVISOR_SCOPE):",
                   " if manifest.get('scope') in (DAILY_SCOPE,ADVISOR_SCOPE,INSIGHTS_SCOPE):")
    code = replace(code, "(ADVISOR_TARGETS if manifest.get('scope')==ADVISOR_SCOPE else DAILY_TARGETS).values():",
                   "(DAILY_TARGETS if manifest.get('scope')==DAILY_SCOPE else ADVISOR_TARGETS).values():")
    # Existing range restart/health, collector lock, apply and recovery dispatch.
    if code.count('DAILY_SCOPE,ADVISOR_SCOPE):') != 4:
        raise ValueError('publisher activation shape changed')
    code = code.replace('DAILY_SCOPE,ADVISOR_SCOPE):', 'DAILY_SCOPE,ADVISOR_SCOPE,INSIGHTS_SCOPE):')
    out = ROOT / 'insights-release'
    candidate = out / 'candidate' / CANDIDATE
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_bytes(payload)
    (out / 'approved-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', 'utf-8')
    (out / 'release_navigation.py').write_bytes(code.encode('utf-8'))
    print(json.dumps({'scope': SCOPE, 'files': 1, 'releaseReady': False,
                      'manifestSha256': hashlib.sha256((out / 'approved-manifest.json').read_bytes()).hexdigest()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dependencies', type=Path, help='Fresh exact five-file shared SHA list; no credentials.')
    build(parser.parse_args().dependencies)
