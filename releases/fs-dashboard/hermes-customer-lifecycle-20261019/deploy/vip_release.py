"""Prepare and inspect the eight VIP files using the existing navigation publisher."""
import hashlib
import json
import re
import sqlite3
import stat
import subprocess
import sys
import types
import urllib.request
from contextlib import closing
from pathlib import Path
from zipfile import ZipFile


HERE = Path(__file__).resolve().parent
SCOPE = 'hermes-vip-maintenance-20261120'
BASE_SHA = '1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
RELEASE = 'releases/fs-dashboard/hermes-customer-lifecycle-20261019'
BASE_REPO = 'releases/fs-dashboard/hermes-conversation-20261018/deploy/release_navigation_base.py'
PRIOR = '/opt/fs-release-stage/customer-buyer-tracking-20261110-pr976-998bd06/approved-manifest.json'
HERMES = '/opt/fs-hermes-fc'
RANGE = '/opt/fs-exact-range-20261001'
STATIC = '/var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565'
TRACKING_DB = '/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db'
CONVERSATIONS_DB = '/var/lib/fs-hermes-fc/fs/conversations/conversations.db'
TARGETS = {'source/' + name: HERMES + '/' + name for name in (
    'tracking_controller.py', 'vip_maintenance.py', 'vip_followup.py', 'vip_query.py', 'nightly_data.py')}
TARGETS.update({'source/' + name: STATIC + '/' + name for name in ('index.html', 'page.js', 'page.css')})
REPO_FILES = {key: RELEASE + '/' + key for key in TARGETS}
REPO_FILES.update({'source/' + name: RELEASE + '/frontend/' + name for name in ('index.html', 'page.js', 'page.css')})
REPO_FILES['source/nightly_data.py'] = 'releases/fs-dashboard/nightly-reschedule-20261025/source/nightly_data.py'
BEFORE = {
    'source/tracking_controller.py': '57175f44ec45a5e044dd24e29d1b623a47df8e91b20e2ce2e37ce759120bcac8',
    'source/nightly_data.py': '3b53203e85a9337ef52934116c5eb17e4df6655d0437ef5cc298866667ec3d53',
    'source/index.html': '7c92e176c1ee8f7946bda98c510f72590db52854c52baefdf4e0f205ca1a9ce4',
    'source/page.js': 'dd2763ee5c34bb9e3349eaeb90718bed2e6e4458c33db04705ad6ef3c2ef38df',
    'source/page.css': 'e613219c73c7867b530bd45d578c979b4ebbb75486a722f91d02c7ccf9bc662e',
    'source/vip_maintenance.py': None,
    'source/vip_followup.py': None,
    'source/vip_query.py': None,
}
RUNTIME = {unit: {'ActiveState': 'active'} for unit in ('fs-hermes-fc.service', 'fs-business-range.service', 'nginx.service')}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def version(value):
    if not re.fullmatch('[a-f0-9]{40}', value or ''):
        raise ValueError('vip_source_commit_required')
    return value


def bundle(repo, output, commit):
    commit = version(commit)

    def git_blob(path):
        return subprocess.check_output(['git', '-C', str(repo), 'cat-file', 'blob', f'{commit}:{path}'])

    candidates = {name: git_blob(path) for name, path in REPO_FILES.items()}
    base = git_blob(BASE_REPO)
    if sha(base) != BASE_SHA:
        raise ValueError('vip_frozen_publisher_drift')
    proof = dict(sourceCommit=commit, sha256={name: sha(raw) for name, raw in candidates.items()})
    with ZipFile(output, 'x') as archive:
        archive.writestr('vip_release.py', git_blob(RELEASE + '/deploy/vip_release.py'))
        archive.writestr('release_navigation_base.py', base)
        archive.writestr('source-proof.json', encoded(proof))
        for name, raw in candidates.items():
            archive.writestr('candidate/' + name, raw)
    return dict(sourceCommit=commit, payloads=len(candidates), archiveSha256=sha(Path(output).read_bytes()))


def path_in(root, target):
    return root / target.lstrip('/')


def checked_file(path):
    if any(part.is_symlink() for part in (path, *path.parents)) or path.exists() and not path.is_file():
        raise ValueError('vip_release_invalid_path: ' + str(path))
    return path


def proof_for(stage):
    proof = json.loads((stage / 'source-proof.json').read_bytes())
    version(proof['sourceCommit'])
    if set(proof['sha256']) != TARGETS.keys():
        raise ValueError('vip_exact_source_set_required')
    for name, expected in proof['sha256'].items():
        candidate = checked_file(stage / 'candidate' / name)
        raw = candidate.read_bytes()
        if sha(raw) != expected:
            raise ValueError('vip_candidate_source_drift: ' + name)
        if name.endswith('.py'):
            compile(raw, name, 'exec')
    return proof


def prepare(stage, root=Path('/')):
    proof = proof_for(stage)
    old = json.loads(path_in(root, PRIOR).read_bytes())
    rows = []
    for name, target in TARGETS.items():
        path = checked_file(path_in(root, target))
        existing = path.exists()
        if (sha(path.read_bytes()) if existing else None) != BEFORE[name]:
            raise ValueError('vip_live_baseline_changed: ' + target)
        if existing:
            info = path.stat()
            if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink) != (0, 0, 0o644, 1):
                raise ValueError('vip_target_owner_mode_drift: ' + target)
        rows.append(dict(candidate=name, target=target, beforeSha256=BEFORE[name],
                         sha256=proof['sha256'][name], owner='0:0', mode='0o644'))
    names = ({row['path'] for row in old['unchangedRequired']} |
             {row['target'] for row in old['files']}) - set(TARGETS.values())
    protected = []
    for name in sorted(names):
        path = checked_file(path_in(root, name))
        if path.exists():
            protected.append(dict(path=name, sha256=sha(path.read_bytes())))
    manifest = dict(schemaVersion=1, scope=SCOPE, releaseReady=True, sourceCommit=proof['sourceCommit'],
                    imageId=old['imageId'], businessWrites=False, timersChanged=False, runtimeRequired=RUNTIME,
                    files=rows, unchangedRequired=protected)
    payload = encoded(manifest)
    with (stage / 'approved-manifest.json').open('xb') as stream:
        stream.write(payload)
    return dict(sourceCommit=proof['sourceCommit'], payloads=len(rows), protected=len(protected), manifestSha256=sha(payload))


def tracking_quiescent(base, root):
    idle = {
        TRACKING_DB: {'scan_jobs': ('pending',), 'milestones': ('claimed', 'creating', 'dispatch_unknown', 'queued', 'running')},
        CONVERSATIONS_DB: {'turns': ('preparing', 'dispatch_unknown', 'queued', 'running', 'stopping')},
    }
    for target, tables in idle.items():
        path = base.rooted(root, target)
        base.no_target_link(path)
        if not path.exists():
            continue
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            for table, states in tables.items():
                marks = ','.join('?' for _ in states)
                if db.execute(f'SELECT 1 FROM {table} WHERE state IN ({marks}) LIMIT 1', states).fetchone():
                    raise ValueError('vip_existing_job_in_flight: ' + table)
            if target == TRACKING_DB and db.execute("SELECT 1 FROM sqlite_master WHERE name='vip_refresh'").fetchone():
                if db.execute("SELECT 1 FROM vip_refresh WHERE status='pending' AND "
                              "datetime(attempted_at) > datetime('now','-30 minutes')").fetchone():
                    raise ValueError('vip_refresh_in_flight')
    if root == Path('/'):
        with urllib.request.urlopen('http://127.0.0.1:8931/health', timeout=3) as response:
            health = json.load(response)
        if health.get('ok') is not True or health.get('active_customer_reports', 0) != 0:
            raise ValueError('vip_range_or_customer_reports_busy')


def load_base(stage=HERE):
    raw = (stage / 'release_navigation_base.py').read_bytes()
    if sha(raw) != BASE_SHA:
        raise ValueError('vip_frozen_publisher_drift')
    source = raw.decode()
    for old, new in (
        ("HERMES_HISTORY_SCOPE='hermes-fc-history-pagination-20261014'", f"HERMES_HISTORY_SCOPE='{SCOPE}'"),
        ("if any(r.get('beforeSha256') is None for r in files if not ((",
         "if any(r.get('beforeSha256') is None for r in files if r['target'] not in VIP_FIRST_INSTALL and not (("),
    ):
        if source.count(old) != 1:
            raise ValueError('vip_frozen_publisher_anchor_drift')
        source = source.replace(old, new)
    base = types.ModuleType('vip_frozen_publisher')
    base.__file__ = str(stage / 'release_navigation_base.py')
    base.VIP_FIRST_INSTALL = {TARGETS[key] for key in BEFORE if BEFORE[key] is None}
    exec(compile(source, base.__file__, 'exec'), base.__dict__)
    base.HERMES_HISTORY_TARGETS = TARGETS

    original_target = base.target_for
    base.target_for = lambda name: TARGETS[name] if name in TARGETS else original_target(name)
    original_files = base.expected_files
    base.expected_files = lambda manifest: set(TARGETS) if manifest.get('scope') == SCOPE else original_files(manifest)
    original_quiescent = base.hermes_quiescent

    def quiescent(root):
        original_quiescent(root)
        tracking_quiescent(base, root)

    base.hermes_quiescent = quiescent
    approved = json.loads((stage / 'approved-manifest.json').read_bytes())
    original_validate = base.validate

    def validate(manifest, candidate_stage):
        proof = proof_for(candidate_stage)
        rows = manifest['files']
        if (manifest != approved or manifest.get('scope') != SCOPE or manifest.get('sourceCommit') != proof['sourceCommit']
                or len(rows) != len(TARGETS) or {row['candidate']: row['target'] for row in rows} != TARGETS
                or manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False
                or manifest.get('runtimeRequired') != RUNTIME):
            raise ValueError('vip_exact_manifest_required')
        for row in rows:
            name = row['candidate']
            if (row.get('beforeSha256') != BEFORE[name] or row.get('sha256') != proof['sha256'][name]
                    or row.get('owner') != '0:0' or row.get('mode') != '0o644'):
                raise ValueError('vip_manifest_file_drift: ' + name)
        return original_validate(manifest, candidate_stage)

    base.validate = validate
    original_inspect = base.inspect

    def inspect(manifest, candidate_stage, root=Path('/')):
        result = original_inspect(manifest, candidate_stage, root)
        if root == Path('/'):
            run_composed_import(candidate_stage)
        return result

    base.inspect = inspect
    return base


def run_composed_import(stage):
    candidate = stage / 'candidate/source'
    program = """import sys
from pathlib import Path
candidate = Path(sys.argv[1])
sys.path[:0] = [str(candidate), '/opt/fs-hermes-fc', '/opt/fs-exact-range-20261001']
import tracking_controller, vip_query, vip_followup, vip_maintenance, nightly_data
assert all(Path(module.__file__).resolve().parent == candidate for module in (
    tracking_controller, vip_query, vip_followup, vip_maintenance, nightly_data))
assert callable(vip_followup.read_cohort) and callable(vip_followup.refresh_buyers)
assert callable(vip_maintenance.vip_weekly_report)
assert callable(nightly_data.report_context)
"""
    subprocess.run([sys.executable, '-I', '-B', '-c', program, str(candidate)], timeout=20, check=True)


def main(action, *args):
    if action == 'bundle' and len(args) == 3:
        result = bundle(Path(args[0]), Path(args[1]), args[2])
    elif action == 'prepare' and not args:
        result = prepare(HERE)
    else:
        load_base().main()
        return
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main(*sys.argv[1:])
