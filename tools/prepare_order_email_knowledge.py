"""Offline knowledgeOnly overlay, never publish or operate services.

Input: snapshot/policy.json (raw deployed policy) and its complete catalog and
source_root trees mirrored relative to /var/lib/fs-hermes-fc/fs. Every referenced
catalog must be beneath knowledge-releases/, with an explicit source_root there.
Output must not exist. Sources/adapters come from --commit, never working files.
The caller verifies merged-main/CI and snapshot freshness separately; the manifest
always remains releaseReady=false until the lead's original-publisher preflight.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import types

ROOT = Path(__file__).resolve().parents[1]
MODULE = 'releases/fs-dashboard/knowledge-layering-20261023'
EMAIL = 'fs.orders.email_export'
OVERLAYS = (EMAIL, 'fs.data.sources')


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


def prepare(root, snapshot, output, commit):
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
    for identity in OVERLAYS:
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
    release = 'fc-reporting-knowledge-20261105-' + commit[:8]
    release_root = 'knowledge-releases/' + release
    payloads, remap, checks = {}, {}, []
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
                    payloads['artifact/' + sources + item.relative_to(old_tree).as_posix()] = safe.read_bytes()
        for row in index['entries']:
            # Deployed candidate rows may have no artifact; they are never selected.
            if row['layer'] == 'candidate':
                continue
            source = row['source']
            data = bound(snapshot, source_root + '/' + source['path']).read_bytes()
            normalized = data.replace(b'\r\n', b'\n') if source.get('hash_basis') == 'utf8_lf' else data
            if sha(normalized) != source['sha256']:
                raise ValueError('snapshot_source_changed:' + row['id'])
            catalog.extract(normalized.decode('utf-8-sig'), source.get('selector'))
        payloads['artifact/originals/' + (slot or 'root/') + 'index.json'] = raw
        for identity, template in current.items():
            existing = [r for r in index['entries'] if r['id'] == identity and r['layer'] == 'current']
            if len(existing) > 1 or any(r['status'] != 'effective' for r in existing):
                raise ValueError('snapshot_current_conflict:' + identity)
            row = copy.deepcopy(template)
            source = row['source']
            canonical_path = source['path']
            data = git_bytes(root, commit, canonical_path)
            normalized = data.replace(b'\r\n', b'\n') if source.get('hash_basis') == 'utf8_lf' else data
            if sha(normalized) != source['sha256']:
                raise ValueError('canonical_source_changed:' + identity)
            catalog.extract(normalized.decode('utf-8-sig'), source.get('selector'))
            source.update(path='overlay/' + canonical_path, canonical_path=canonical_path)
            key = 'artifact/' + sources + source['path']
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
        route['catalog'], route['sha256'], _ = remap[route['catalog']]
        if 'entry_ids' in route and EMAIL not in route['entry_ids']:
            route['entry_ids'].append(EMAIL)
        checks.append(copy.deepcopy(route))
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
    publisher.targets(manifest)
    adapters = {'release.py': MODULE + '/deploy/release.py',
                'release_adapter_base.py': 'releases/fs-dashboard/fs-business-baseline-20261021/deploy/release.py',
                'release_navigation_base.py': 'releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py'}
    copies = {name: git_bytes(root, commit, path) for name, path in adapters.items()}
    output.mkdir(parents=True)
    for name, data in payloads.items():
        path = output / 'candidate' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    # select() resolves source_root from the fs root, NOT from the catalog directory.
    # Use a separate local validation mirror with the exact deployed relative paths.
    mirror = output / 'validation-fs-root'
    for name, data in payloads.items():
        if name.startswith('artifact/'):
            path = mirror / release_root / name[len('artifact/'):]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    for route in checks:
        selected = catalog.select(mirror, route['catalog'], route['sha256'], route['modules'], route.get('entry_ids'))
        if selected['status'] != 'available' or EMAIL not in [r['id'] for r in selected['entries']]:
            raise ValueError('overlay_selection_unavailable')
    for name, data in copies.items():
        (output / name).write_bytes(data)
    (output / 'candidate-manifest.json').write_bytes(encoded(manifest))
    return dict(status='offline_candidate_not_published', release=release, stage=str(output),
                catalog_count=len(remap), manifest=manifest)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--commit', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(ROOT, args.snapshot, args.output, args.commit), ensure_ascii=False, indent=2))
