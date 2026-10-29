"""CAS the original wulv/FS/fs route into the immutable V3 catalog."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

from release import PREFIX, RELEASE, RUNTIME, SCOPE, load_base, targets

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent
FS_ROOT = Path('/var/lib/fs-hermes-fc/fs')
OLD_BASELINE_SHA = '4ee3c766966f0eaee05c59d3a01d0186fa34a4c93923403ad3841a2adea6b633'
NEW_BASELINE_SHA = 'e2b79ef71d8c1136ddfa2c1f9bf066c57793503727262f67b9a6a4eb1aa2c972'
OLD_POLICY_SHA = '5dfeae7efd57b25b8f738f217f02ece9a06aabb0afc195924f8e3b2d7ba1dbbe'
OLD_CATALOG = 'knowledge-releases/fc-pricing-v3-20261026-11/index.json'
OLD_CATALOG_SHA = '41202a8f6adbd64cc628fcc3c981e4e4db250f530c5e4d1b8e7b010f79b7789b'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe(path, exists=True):
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('knowledge_symlink_boundary:' + str(item))
    if exists and not path.is_file():
        raise ValueError('knowledge_file_missing:' + str(path))
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError('knowledge_file_type_invalid:' + str(path))


def base_module():
    path = HERE / 'release_navigation_base.py'
    if sha(path) != '57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840':
        raise ValueError('frozen_publisher_drift')
    spec = importlib.util.spec_from_file_location('original_knowledge_publisher', path)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    return base


def prepare():
    if Path(PREFIX).exists():
        raise ValueError('immutable_v3_release_already_exists_reconcile')
    manifest_source = json.loads((STAGE / 'source-manifest.json').read_text(encoding='utf-8'))
    source_commit = manifest_source['sourceCommit']
    for name, expected in manifest_source['payloadSha256'].items():
        path = STAGE / 'candidate' / name
        safe(path)
        if sha(path) != expected:
            raise ValueError('git_payload_sha_mismatch:' + name)
    index_path = STAGE / 'candidate/artifact/index.json'
    if sha(index_path) != manifest_source['catalogSha256']:
        raise ValueError('catalog_source_manifest_mismatch')
    spec = importlib.util.spec_from_file_location('active_knowledge_catalog',
        '/opt/fs-hermes-fc/knowledge_catalog.py')
    catalog = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(catalog)
    index = catalog.validate(json.loads(index_path.read_text(encoding='utf-8')))
    if index['release_state'] != 'published' or index['release'] != RELEASE or \
            index['source_commit'] != source_commit or len(index['entries']) != 25:
        raise ValueError('published_v3_catalog_identity_invalid')
    policy_path = Path(RUNTIME['runtime/knowledge-load-policy.json'])
    safe(policy_path)
    raw = policy_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != OLD_POLICY_SHA:
        raise ValueError('original_knowledge_policy_drift')
    policy = json.loads(raw)
    before = copy.deepcopy(policy)
    routes = policy.get('task_routes', {}).get('routes', [])
    matching = [row for row in routes if (row.get('owner'), row.get('project'), row.get('channel')) == ('wulv', 'FS', 'fs')]
    if policy.get('contract') != 'fs-knowledge-load-policy-v1' or len(matching) != 1:
        raise ValueError('one_original_FS_route_required')
    route = matching[0]
    old_catalog = route.get('catalog')
    if old_catalog != OLD_CATALOG or route.get('sha256') != OLD_CATALOG_SHA:
        raise ValueError('existing_catalog_binding_invalid')
    old_path = FS_ROOT / old_catalog
    safe(old_path)
    if sha(old_path) != route.get('sha256') or route.get('baseline_compatibility') != \
            {'mode': 'retain_full_baseline', 'sha256': OLD_BASELINE_SHA}:
        raise ValueError('existing_catalog_or_full_baseline_binding_drift')
    old_ids = route.get('entry_ids')
    if not isinstance(old_ids, list) or len(old_ids) != 13 or len(set(old_ids)) != 13 or \
            'fc.pricing.v3' not in old_ids:
        raise ValueError('exact_existing_route_entries_required')
    route['catalog'] = 'knowledge-releases/' + RELEASE + '/index.json'
    route['sha256'] = manifest_source['catalogSha256']
    route['entry_ids'] = old_ids
    route['baseline_compatibility']['sha256'] = NEW_BASELINE_SHA
    expected = copy.deepcopy(before)
    old = next(row for row in expected['task_routes']['routes'] if
               (row.get('owner'), row.get('project'), row.get('channel')) == ('wulv', 'FS', 'fs'))
    old.update(catalog=route['catalog'], sha256=route['sha256'], entry_ids=route['entry_ids'])
    old['baseline_compatibility']['sha256'] = NEW_BASELINE_SHA
    if policy != expected:
        raise ValueError('unrelated_policy_delta')
    candidate_policy = STAGE / 'candidate/runtime/knowledge-load-policy.json'
    candidate_policy.parent.mkdir(parents=True, exist_ok=True)
    candidate_policy.write_bytes((json.dumps(policy, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    baseline = Path(RUNTIME['runtime/business-baseline.md'])
    safe(baseline)
    if sha(STAGE / 'candidate/runtime/business-baseline.md') != NEW_BASELINE_SHA or \
            sha(baseline) != OLD_BASELINE_SHA:
        raise ValueError('full_baseline_CAS_drift')
    mapping = {name: PREFIX + name[len('artifact/'):] for name in manifest_source['payloadSha256']
               if name.startswith('artifact/')}
    mapping.update(RUNTIME)
    original = base_module()
    changed = set(mapping.values())
    protected = {'/opt/fs-exact-range-20261001/' + name for name in (
        'boss_insights.py', 'fc_deep_model.py', 'fc_daily.py', 'fc_daily_model.py',
        'fc_detail.py', 'fc_detail_model.py', 'fc_detail_reader.py', 'fc_detail_config.json',
        'fc_deep_sources.py', 'summary_bridge.py')}
    protected.update(('/var/www/dashboard/index.html', '/var/www/dashboard/fs-home/index.html',
        '/var/www/dashboard/fs-home/navigation.js', '/opt/fs-access-policy/access_policy.py',
        '/opt/fc27-cloud-browser/hermes_pricing_bridge.py', str(old_path)))
    protected.update(set(original.HERMES_TARGETS.values()) - changed)
    protected.update((set(original.HERMES_CAPABILITY_TARGETS.values()) |
                     set(original.CAP_PROTECTED_SESSION)) - changed)
    protected.update(set(original.HERMES_DIRECT_TARGETS.values()) - changed)
    rows = []
    for name, target in sorted(mapping.items()):
        path = Path(target)
        safe(path, exists=name in RUNTIME)
        info = path.stat() if path.exists() else None
        if info and (info.st_uid, info.st_gid, info.st_mode & 0o777) != (0, 0, 0o644):
            raise ValueError('knowledge_target_metadata_drift:' + target)
        rows.append(dict(candidate=name, target=target, sha256=sha(STAGE / 'candidate' / name),
                         beforeSha256=sha(path) if info else None, owner='0:0', mode='0o644'))
    guarded = []
    for target in sorted(protected):
        path = Path(target)
        safe(path)
        guarded.append(dict(path=target, sha256=sha(path)))
    runtime = {}
    for unit in ('fs-business-range.service', 'fs-hermes-fc.service'):
        state = subprocess.check_output(['systemctl', 'show', unit, '--no-pager', '-p', 'ActiveState'],
                                        universal_newlines=True).strip()
        if state != 'ActiveState=active':
            raise ValueError('required_Hermes_unit_not_active:' + unit)
        runtime[unit] = {'ActiveState': 'active'}
    manifest = dict(schemaVersion=1, scope=SCOPE, releaseReady=True, sourceCommit=source_commit,
        businessWrites=False, timersChanged=False,
        imageId='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544',
        runtimeRequired=runtime, unchangedRequired=guarded, files=rows)
    targets(manifest)
    approved = HERE / 'approved-manifest.json'
    runtime_path = STAGE / 'approved-manifest.json'
    if approved.exists() or runtime_path.exists():
        raise ValueError('existing_knowledge_manifest_must_be_reconciled')
    bytes_ = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    approved.write_bytes(bytes_)
    os.chmod(approved, 0o600)
    try:
        inspected = load_base().inspect(manifest, STAGE)
        runtime_path.write_bytes(bytes_)
        os.chmod(runtime_path, 0o600)
    except Exception:
        approved.unlink()
        runtime_path.unlink(missing_ok=True)
        raise
    return dict(sourceCommit=source_commit, catalogSha256=manifest_source['catalogSha256'],
                manifestSha256=hashlib.sha256(bytes_).hexdigest(), files=len(rows),
                protected=len(guarded), selectedEntries=len(route['entry_ids']), inspect=inspected)


if __name__ == '__main__':
    print(json.dumps(prepare(), sort_keys=True))
