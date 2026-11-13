"""Offline knowledgeOnly overlay for order email or the D5 shared Admin/ES definitions.

Input: snapshot/policy.json (raw deployed policy) and its complete catalog and
source_root trees mirrored relative to /var/lib/fs-hermes-fc/fs. Every referenced
catalog must be beneath knowledge-releases/, with an explicit source_root there.
Output must not exist. Sources/adapters come from --commit, never working files.
The caller verifies merged-main/CI and snapshot freshness separately; the manifest
always remains releaseReady=false until the lead's original-publisher preflight.
--shared-admin-es additionally takes the retained business-baseline.md and
preflight.json with captured_at, protected file hashes, service states and
existing immutable D5 release names. It performs no publish or service action.
"""
import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import types

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'releases/fs-dashboard/knowledge-layering-20261023'
EMAIL = 'fs.orders.email_export'
OVERLAYS = (EMAIL, 'fs.data.sources')
SHARED_ADMIN_ES = 'fs-fc-admin-es-shared-20261113-r1'
SHARED_BASE_COMMIT = '416167951cfe261d55f2aba299e2cd020a082cf0'
SHARED_OVERLAYS = ('fs.data.sources', 'fs.customer.identity', 'fs.finance.procurement',
                   'fc.marketing.attribution', 'fc.reporting.data')
FS_RUNTIME_ROOT = '/var/lib/fs-hermes-fc/fs/'
BASELINE_TARGET = '/opt/fs-hermes-fc/business-baseline.md'
BASELINE_SOURCE = 'releases/fs-dashboard/fs-business-baseline-20261021/source/hermes/business-baseline.md'
PUBLISHER_IMAGE = 'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def relative(name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or name.startswith('/') or any(p in ('', '.', '..') for p in name.split('/'))):
        raise ValueError('unsafe_snapshot_path:' + str(name))
    return PurePosixPath(name)


def bound(root, name):
    path = root.joinpath(*relative(name).parts)
    for item in (path, *path.parents):
        info = item.lstat()
        if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('snapshot_link:' + str(item))
        if item == root:
            return path
    raise ValueError('snapshot_boundary')


def git_bytes(root, commit, name):
    return subprocess.check_output(['git', 'show', commit + ':' + name], cwd=root)


def pinned_module(root, commit, name):
    module = types.ModuleType(name)
    module.__file__ = str(root / name)
    exec(compile(git_bytes(root, commit, name), name, 'exec'), module.__dict__)
    return module


def routes(policy):
    yield from policy.get('requests', {}).values()
    yield from policy.get('task_routes', {}).get('routes', [])
    yield from policy.get('native', {}).get('routes', [])


def normalized(data, source):
    return data.replace(b'\r\n', b'\n') if source.get('hash_basis') == 'utf8_lf' else data


def shared_changes(root, commit, catalog, canonical, current):
    if (canonical.get('release') != SHARED_ADMIN_ES or canonical.get('release_state') != 'candidate'
            or canonical.get('source_commit') is not None or canonical.get('base_commit') != SHARED_BASE_COMMIT):
        raise ValueError('exact_shared_admin_es_candidate_required')
    prior = json.loads(git_bytes(root, SHARED_BASE_COMMIT, 'knowledge/index.json'))
    changes = {}
    for identity, row in current.items():
        if row['revision'] != SHARED_ADMIN_ES:
            raise ValueError('shared_admin_es_revision_invalid:' + identity)
        previous = next(r for r in prior['entries'] if r['id'] == identity and r['layer'] == 'current')
        selected = []
        for revision, template in ((SHARED_BASE_COMMIT, previous), (commit, row)):
            source = template['source']
            data = normalized(git_bytes(root, revision, source['path']), source)
            if sha(data) != source['sha256']:
                raise ValueError('canonical_source_changed:' + identity)
            selected.append(catalog.extract(data.decode('utf-8-sig'), source.get('selector')))
        old, new = (text.splitlines(keepends=True) for text in selected)
        # One line of unchanged context uniquely anchors the small D5 edits while
        # retaining the distinct finance and attribution wording in live catalogs.
        changes[identity] = [
            (''.join(old[group[0][1]:group[-1][2]]), ''.join(new[group[0][3]:group[-1][4]]))
            for group in difflib.SequenceMatcher(None, old, new, autojunk=False).get_grouped_opcodes(1)
        ]
        if not changes[identity]:
            raise ValueError('shared_admin_es_delta_missing:' + identity)
    return changes


def merge_shared_entry(identity, template, row, content, changes):
    for old, new in changes[identity]:
        if content.count(old) != 1:
            raise ValueError('shared_admin_es_snapshot_merge_conflict:' + identity)
        content = content.replace(old, new, 1)
    data = (content.rstrip('\n') + '\n').encode('utf-8')
    source = template['source']
    row.update(revision=template['revision'], knowledge_updated_at=template['knowledge_updated_at'],
               source=dict(path='overlay/' + identity + '.md', sha256=sha(data), hash_basis='utf8_lf',
                           canonical_path=source['path'], canonical_sha256=source['sha256']),
               provenance=row['provenance'] + template['provenance'],
               supersedes=list(dict.fromkeys(row['supersedes'] + template['supersedes'])))
    return data


def shared_preflight(root, snapshot, commit, release):
    info = json.loads(bound(snapshot, 'preflight.json').read_bytes())
    if release in info['immutable_directories']:
        raise ValueError('shared_admin_es_release_already_exists_reconcile')
    baseline = bound(snapshot, 'business-baseline.md').read_bytes()
    proof = json.loads(git_bytes(root, commit, BASELINE_SOURCE.replace('.md', '.provenance.json')))
    digest = sha(baseline)
    if (digest != info['protected'][BASELINE_TARGET] or digest != proof['after_sha256']
            or baseline != git_bytes(root, commit, BASELINE_SOURCE)
            or proof['contract'] != 'fc-current-baseline-patch-v1' or proof['runtime_source'] != BASELINE_SOURCE
            or not re.fullmatch('[a-f0-9]{64}', proof['canonical_sha256'])):
        raise ValueError('shared_admin_es_retained_baseline_provenance_invalid')
    units = {'fs-hermes-fc.service', 'fs-business-range.service'}
    if info['runtime'] != {name: {'ActiveState': 'active'} for name in units}:
        raise ValueError('shared_admin_es_active_services_required')
    return info, proof


def verify_routes(catalog, mirror, snapshot, checks, shared_admin_es, current):
    for before, route in checks:
        selected = catalog.select(mirror, route['catalog'], route['sha256'], route['modules'], route.get('entry_ids'))
        if selected['status'] != 'available':
            raise ValueError('overlay_selection_unavailable')
        if shared_admin_es:
            original = catalog.select(snapshot, before['catalog'], before['sha256'], before['modules'],
                                      before.get('entry_ids'))
            old_entries = {r['id']: r for r in original['entries']}
            if original['status'] != 'available' or set(old_entries) != {r['id'] for r in selected['entries']}:
                raise ValueError('shared_admin_es_route_selection_changed')
            for row in selected['entries']:
                if row['id'] not in current:
                    old = old_entries[row['id']]
                    if (row['revision'], row['content_sha256']) != (old['revision'], old['content_sha256']):
                        raise ValueError('shared_admin_es_unrelated_selection_changed:' + row['id'])
        elif EMAIL not in [r['id'] for r in selected['entries']]:
            raise ValueError('overlay_selection_unavailable')


def write_payloads(root, payloads):
    for name, data in payloads.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def prepare(root, snapshot, output, commit, *, shared_admin_es=False):
    root, snapshot, output = Path(root).absolute(), Path(snapshot).absolute(), Path(output).absolute()
    if not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('full_source_commit_required')
    if output.exists() or output.is_symlink():
        raise ValueError('stage_already_exists_reconcile_original')
    if snapshot == output or snapshot in output.parents or output in snapshot.parents:
        raise ValueError('snapshot_output_overlap')
    catalog = pinned_module(root, commit, MODULE + '/source/knowledge_catalog.py')
    publisher = pinned_module(root, commit, MODULE + '/deploy/release.py')
    canonical = json.loads(git_bytes(root, commit, 'knowledge/index.json'))
    current = {}
    for identity in SHARED_OVERLAYS if shared_admin_es else OVERLAYS:
        found = [r for r in canonical['entries'] if r['id'] == identity
                 and r['layer'] == 'current' and r['status'] == 'effective']
        if len(found) != 1:
            raise ValueError('canonical_current_required:' + identity)
        current[identity] = found[0]
    policy_raw = bound(snapshot, 'policy.json').read_bytes()
    policy = json.loads(policy_raw)
    if policy.get('contract') != 'fs-knowledge-load-policy-v1':
        raise ValueError('knowledge_policy_contract')
    all_routes = list(routes(policy))
    if not all_routes:
        raise ValueError('snapshot_routes_required')
    release = SHARED_ADMIN_ES + '-' + commit if shared_admin_es else 'fc-reporting-knowledge-20261105-' + commit[:8]
    if shared_admin_es:
        changes = shared_changes(root, commit, catalog, canonical, current)
        preflight, baseline_proof = shared_preflight(root, snapshot, commit, release)
        compatibility = {'mode': 'retain_full_baseline', 'sha256': baseline_proof['after_sha256']}
        if any(r.get('baseline_compatibility', compatibility) != compatibility for r in all_routes):
            raise ValueError('shared_admin_es_baseline_binding_drift')
    release_root = 'knowledge-releases/' + release
    payloads, remap, checks = {}, {}, []
    shared_rows = []
    for route in all_routes:
        old_name = route['catalog']
        relative(old_name)
        if not old_name.startswith('knowledge-releases/'):
            raise ValueError('snapshot_release_boundary')
        if old_name in remap:
            if route['sha256'] != remap[old_name][2]:
                raise ValueError('snapshot_catalog_hash_conflict')
            continue
        raw = bound(snapshot, old_name).read_bytes()
        if sha(raw) != route['sha256']:
            raise ValueError('snapshot_catalog_changed:' + old_name)
        index = catalog.validate(json.loads(raw))
        if shared_admin_es and (index['release_state'] != 'published'
                or preflight['protected'].get(FS_RUNTIME_ROOT + old_name) != sha(raw)):
            raise ValueError('shared_admin_es_catalog_cas_invalid:' + old_name)
        source_root = index.get('source_root', '')
        relative(source_root)
        if not source_root.startswith('knowledge-releases/'):
            raise ValueError('snapshot_source_root_boundary')
        # Preserve each catalog independently: FC patches need not match each other.
        slot = '' if not remap else 'catalog-' + str(len(remap)) + '/'
        new_name = slot + 'index.json'
        sources = slot + 'sources/'
        old_tree = bound(snapshot, source_root)
        if not old_tree.is_dir():
            raise ValueError('snapshot_source_tree_required')
        for directory, dirs, files in os.walk(old_tree, followlinks=False):
            for name in dirs + files:
                item = Path(directory) / name
                rel = item.relative_to(snapshot).as_posix()
                safe = bound(snapshot, rel)
                if safe.is_file():
                    data = safe.read_bytes()
                    if shared_admin_es and preflight['protected'].get(FS_RUNTIME_ROOT + rel) != sha(data):
                        raise ValueError('shared_admin_es_source_cas_invalid:' + rel)
                    payloads['artifact/' + sources + item.relative_to(old_tree).as_posix()] = data
        for row in index['entries']:
            # Deployed candidate rows may have no artifact; they are never selected.
            if row['layer'] == 'candidate':
                continue
            source = row['source']
            data = bound(snapshot, source_root + '/' + source['path']).read_bytes()
            source_data = normalized(data, source)
            if sha(source_data) != source['sha256']:
                raise ValueError('snapshot_source_changed:' + row['id'])
            catalog.extract(source_data.decode('utf-8-sig'), source.get('selector'))
        payloads['artifact/originals/' + (slot or 'root/') + 'index.json'] = raw
        for identity, template in current.items():
            existing = [r for r in index['entries'] if r['id'] == identity and r['layer'] == 'current']
            if len(existing) > 1 or any(r['status'] != 'effective' for r in existing):
                raise ValueError('snapshot_current_conflict:' + identity)
            if shared_admin_es:
                if not existing:
                    continue
                row = copy.deepcopy(existing[0])
                original_source = existing[0]['source']
                body = payloads['artifact/' + sources + original_source['path']]
                content = catalog.extract(normalized(body, original_source).decode('utf-8-sig'),
                                          original_source.get('selector'))
                data = merge_shared_entry(identity, template, row, content, changes)
                shared_rows.append(dict(catalog=old_name, id=identity, previous_revision=existing[0]['revision'],
                                        previous_source_sha256=original_source['sha256'], revision=row['revision'],
                                        source_sha256=row['source']['sha256']))
            else:
                row = copy.deepcopy(template)
                source = row['source']
                canonical_path = source['path']
                data = git_bytes(root, commit, canonical_path)
                source_data = normalized(data, source)
                if sha(source_data) != source['sha256']:
                    raise ValueError('canonical_source_changed:' + identity)
                catalog.extract(source_data.decode('utf-8-sig'), source.get('selector'))
                source.update(path='overlay/' + canonical_path, canonical_path=canonical_path)
            key = 'artifact/' + sources + row['source']['path']
            if key in payloads and payloads[key] != data:
                raise ValueError('overlay_path_collision')
            payloads[key] = data
            row['source_commit'] = commit
            if existing:
                row['supersedes'] = list(dict.fromkeys(row['supersedes'] + [identity + '@' + existing[0]['revision']]))
                index['entries'][index['entries'].index(existing[0])] = row
            else:
                index['entries'].append(row)
        index.update(release=release, release_state='published', source_commit=commit,
                     source_root=release_root + '/' + sources.rstrip('/'))
        catalog.validate(index)
        data = encoded(index)
        payloads['artifact/' + new_name] = data
        remap[old_name] = (release_root + '/' + new_name, sha(data), route['sha256'])
    for route in all_routes:
        before = copy.deepcopy(route)
        route['catalog'], route['sha256'], _ = remap[route['catalog']]
        if not shared_admin_es and 'entry_ids' in route and EMAIL not in route['entry_ids']:
            route['entry_ids'].append(EMAIL)
        checks.append((before, copy.deepcopy(route)))
    payloads['runtime/knowledge-load-policy.json'] = encoded(policy)
    payloads['artifact/originals/policy.json'] = policy_raw
    prefix = '/var/lib/fs-hermes-fc/fs/' + release_root + '/'
    manifest = dict(schemaVersion=1, scope=publisher.SCOPE, knowledgeOnly=True,
                    knowledgeRelease=release, sourceCommit=commit, releaseReady=False,
                    businessWrites=False, timersChanged=False, unchangedRequired=[], runtimeRequired={},
                    files=[dict(candidate=name, target=('/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json'
                           if name.startswith('runtime/') else prefix + name[len('artifact/'):]),
                           sha256=sha(data), beforeSha256=None, owner='0:0', mode='0o644')
                           for name, data in sorted(payloads.items())])
    if shared_admin_es:
        if {row['id'] for row in shared_rows} != set(SHARED_OVERLAYS):
            raise ValueError('shared_admin_es_overlay_inventory_invalid')
        policy_row = next(row for row in manifest['files'] if row['candidate'] == 'runtime/knowledge-load-policy.json')
        policy_row['beforeSha256'] = sha(policy_raw)
        manifest.update(imageId=PUBLISHER_IMAGE, runtimeRequired=preflight['runtime'],
                        unchangedRequired=[dict(path=path, sha256=digest)
                                           for path, digest in sorted(preflight['protected'].items())])
    publisher.targets(manifest)
    adapters = {'release.py': MODULE + '/deploy/release.py',
                'release_adapter_base.py': 'releases/fs-dashboard/fs-business-baseline-20261021/deploy/release.py',
                'release_navigation_base.py': 'releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py'}
    copies = {name: git_bytes(root, commit, path) for name, path in adapters.items()}
    # select() resolves source_root from the fs root, NOT from the catalog directory.
    # Use a separate local validation mirror with the exact deployed relative paths.
    mirror_payloads = {release_root + '/' + name[len('artifact/'):]: data for name, data in payloads.items()
                       if name.startswith('artifact/')}
    with tempfile.TemporaryDirectory(prefix='kl-') as folder:
        mirror = Path(folder)
        write_payloads(mirror, mirror_payloads)
        verify_routes(catalog, mirror, snapshot, checks, shared_admin_es, current)
    output.mkdir(parents=True)
    write_payloads(output / 'candidate', payloads)
    if not shared_admin_es:
        write_payloads(output / 'validation-fs-root', mirror_payloads)
    for name, data in copies.items():
        (output / name).write_bytes(data)
    (output / 'candidate-manifest.json').write_bytes(encoded(manifest))
    if shared_admin_es:
        (output / 'retained-baseline-provenance.json').write_bytes(encoded(dict(
            observed_at=preflight['captured_at'], target=BASELINE_TARGET,
            retained_sha256=preflight['protected'][BASELINE_TARGET], existing_provenance=baseline_proof,
            overlays=shared_rows)))
    return dict(status='offline_candidate_not_published', release=release, stage=str(output),
                catalog_count=len(remap), manifest=manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--shared-admin-es', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(ROOT, args.snapshot, args.output, args.commit, shared_admin_es=args.shared_admin_es),
                     ensure_ascii=False, indent=2))
