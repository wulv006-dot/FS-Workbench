"""Build LF Git payloads and fresh on-host stages; never write active targets."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess

from runtime_release import (HERE, NGINX, TARGETS, NEW, FROZEN_IMAGE_MARKER, frozen,
                             protected_paths, worker_observation, INSTALLED_COMMIT,
                             INSTALLED_PROOF, INSTALLED_NGINX_SHA, installed_baseline)

MODULE = 'releases/fs-dashboard/hermes-conversation-20261018/'
CORE = 'releases/fs-dashboard/hermes-v2-core-20261020/source/'
FC = 'releases/fc-coins/'
PUBLISHER_SOURCES = {name: MODULE + 'deploy/' + name for name in (
    'runtime_release.py', 'runtime_prepare.py', 'release_navigation_base.py')}
PUBLISHER_SOURCES['release_readiness.py'] = FC + 'fc-pricing-v3-20261026/deploy/release_readiness.py'
SOURCES = {name: MODULE + 'source/' + name.rsplit('/', 1)[1] for name in (
    'runtime/conversation_store.py', 'runtime/conversation_files.py', 'runtime/conversation_file_bindings.py')}
SOURCES.update({name: CORE + name.rsplit('/', 1)[1] for name in (
    'runtime/conversation_file_tools.py', 'runtime/material_evidence.py')})
SOURCES.update({'runtime/conversation_service.py': FC + 'fc-pricing-v3-20261026/source/conversation_service.py',
                'runtime/runs_contract.py': FC + 'fc-pricing-v2-20261022/source/runs_contract.py',
                'runtime/proxy_gateway.py': FC + 'fc-review-channel-20261026/source/proxy_gateway.py',
                'runtime/hermes_worker.py': FC + 'fc-review-channel-20261026/source/hermes_worker.py',
                'http/conversation_http.py': FC + 'fc-pricing-v3-20261026/source/conversation_http.py'})
SOURCES.update({'frontend/' + name: MODULE + 'frontend/' + name
                for name in ('index.html', 'conversation.js', 'conversation.css')})
KNOWN = {
    'runtime/conversation_service.py': 'cfb06ef0321b9b2c1454956e585583809ec904be74e9803dd28e983edd3cbcc6',
    'runtime/conversation_store.py': '43d4f8bf1e67b86f9beb0ee87903c41cb62d9c86079c2c6a68a8d7b0c586fb45',
    'runtime/runs_contract.py': 'e02e94b83325f7aa1ec1b598cf25f11d26e77ec481d25bdd6fab9ffd9765c70c',
    'runtime/proxy_gateway.py': '784257f2e99340128c8163d92f8c2cf79c3229ebe952ff821687e9655705d3ff',
    'runtime/hermes_worker.py': '8c377abb19da520df2f92e02e0523430dd53fc1be2f1eac8c47c3f6de35854e9',
    'http/conversation_http.py': 'd74f0242b2d22a210f694218c0d5e1933af581f0c1e137f658fcb882f5b058b7',
    'frontend/index.html': '3d79a5642f1517a8c1e414702c2b7491dc0ff4ed079c7d09895a3b1251045a24',
    'frontend/conversation.js': '81debe079db8fdb83eff6145af55c743895871f65acbfb143841f93cff9226b6',
    'frontend/conversation.css': '68f1803296d5b6057ada86f569d8d26606f2b37a7a6178cf855b287c986cc029',
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def patch_nginx(raw):
    """Only change the two existing conversation limits; retain every other byte."""
    result, count = [], 0
    lines = raw.splitlines(keepends=True)
    index = 0
    markers = (b'location = /api/hermes/conversations {', b'location ^~ /api/hermes/conversations/ {')
    seen = set()
    while index < len(lines):
        marker = lines[index].strip()
        if marker not in markers:
            result.append(lines[index]); index += 1
            continue
        if marker in seen:
            raise ValueError('duplicate_conversation_location')
        seen.add(marker)
        block, depth = [], 0
        while index < len(lines):
            row = lines[index]; index += 1; block.append(row)
            depth += row.count(b'{') - row.count(b'}')
            if depth == 0:
                break
        if depth:
            raise ValueError('conversation_location_unclosed')
        changed, n = re.subn(rb'(?m)^([ \t]*client_max_body_size[ \t]+)16k([ \t]*;)',
                             rb'\g<1>10m\g<2>', b''.join(block))
        if n != 1:
            raise ValueError('conversation_limit_anchor_drift')
        count += n; result.append(changed)
    if count != 2:
        raise ValueError('exact_conversation_locations_required')
    return b''.join(result)


def file_metadata(base, root, name, absent=False):
    path = base.rooted(root, name)
    base.no_target_link(path)
    if not path.exists():
        if not absent:
            raise ValueError('required_runtime_path_missing: ' + name)
        return {'path': name, 'sha256': None}
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != 0 or info.st_gid != 0:
        raise ValueError('runtime_regular_root_file_required: ' + name)
    return {'path': name, 'sha256': digest(path.read_bytes()), 'mode': oct(stat.S_IMODE(info.st_mode))}


def observe(root=Path('/'), installed=None):
    base = frozen()
    rows = {name: file_metadata(base, root, target, not installed and name in NEW) for name, target in TARGETS.items()}
    expected = {row['candidate']: row['sha256'] for row in installed['files']} if installed else KNOWN
    for name, row in rows.items():
        if (not installed and name in NEW and row['sha256'] is not None) or (name in expected and row['sha256'] != expected[name]):
            raise ValueError('runtime_source_baseline_drift: ' + row['path'])
        expected_mode = '0o600' if row['path'] == NGINX else '0o644'
        if row['sha256'] is not None and row['mode'] != expected_mode:
            raise ValueError('runtime_mode_drift: ' + row['path'])
    protected = [file_metadata(base, root, path) for path in sorted(protected_paths(base))]
    if installed and {r['path']: r['sha256'] for r in protected} != {
            r['path']: r['sha256'] for r in installed['unchangedRequired']}:
        raise ValueError('installed_protected_baseline_drift')
    worker = worker_observation(allow_stopped=True) if root == Path('/') else {
        'image': 'sha256:' + '0' * 64, 'state': 'active', 'source': 'container'}
    if installed and worker['image'] != installed['workerImageId']:
        raise ValueError('installed_worker_image_drift')
    return {'observed_at': datetime.now(timezone.utc).isoformat(), 'files': rows, 'protected': protected,
            'worker_image': worker['image'], 'worker_state': worker['state'], 'worker_image_source': worker['source']}


def pack(repo, output, commit):
    if output.exists() or not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('new_payload_and_exact_commit_required')
    output.mkdir(parents=True, mode=0o700)
    paths = {**{'payload/' + name: path for name, path in SOURCES.items()},
             **PUBLISHER_SOURCES}
    hashes = {}
    for name, path in paths.items():
        # Read exact Git bytes: neither Windows autocrlf nor a working copy is a
        # deployment input. This command cannot read credentials outside SOURCES.
        raw = subprocess.check_output(['git', 'show', commit + ':' + path], cwd=repo)
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        hashes[name] = digest(raw)
    baseline = {name: digest(subprocess.check_output(['git', 'show', INSTALLED_COMMIT + ':' + path], cwd=repo))
                for name, path in SOURCES.items()}
    baseline['http/formal.conf'] = INSTALLED_NGINX_SHA
    raw = json.dumps({'source_commit': commit, 'files': hashes,
                      'installed_baseline': {'source_commit': INSTALLED_COMMIT, 'files': baseline}},
                     sort_keys=True).encode('utf-8')
    (output / 'payload-manifest.json').write_bytes(raw)
    return {'source_commit': commit, 'payload_files': len(SOURCES), 'payload_sha256': digest(raw)}


def prepare(payload, stage, commit, payload_sha256, *, root=Path('/'), release_ready=False, followup=False):
    if stage.exists() or not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('new_stage_and_exact_commit_required')
    raw = (payload.parent / 'payload-manifest.json').read_bytes()
    if digest(raw) != payload_sha256:
        raise ValueError('approved_git_payload_required')
    descriptor = json.loads(raw)
    if descriptor.get('source_commit') != commit:
        raise ValueError('payload_source_commit_mismatch')
    expected = {'payload/' + name for name in SOURCES} | set(PUBLISHER_SOURCES)
    if set(descriptor.get('files', {})) != expected:
        raise ValueError('exact_git_payload_required')
    for name, sha in descriptor['files'].items():
        if digest((payload.parent / name).read_bytes()) != sha:
            raise ValueError('git_payload_changed')
    installed = installed_baseline(root, descriptor.get('installed_baseline')) if followup else None
    observed = observe(root, installed)
    # Source verification and body-limit generation happen before creating a stage.
    bodies = {name: (payload / name).read_bytes() for name in SOURCES}
    nginx = frozen().rooted(root, NGINX).read_bytes()
    if digest(nginx) != observed['files']['http/formal.conf']['sha256']:
        raise ValueError('nginx_changed_during_prepare')
    bodies['http/formal.conf'] = nginx if installed else patch_nginx(nginx)
    files = [{'candidate': name, 'target': target, 'beforeSha256': observed['files'][name]['sha256'],
              'sha256': digest(bodies[name]), 'owner': '0:0', 'mode': '0o600' if target == NGINX else '0o644'}
             for name, target in TARGETS.items()]
    from runtime_release import SCOPE
    manifest = {'schemaVersion': 1, 'scope': SCOPE, 'sourceCommit': commit, 'releaseReady': release_ready,
                # Compatibility marker required by the unchanged historical
                # validator, not a claim about today's installed container.
                'imageId': FROZEN_IMAGE_MARKER, 'workerImageId': observed['worker_image'],
                'readinessSha256': descriptor['files']['release_readiness.py'],
                'businessWrites': False, 'timersChanged': False, 'files': files,
                'unchangedRequired': [{'path': r['path'], 'sha256': r['sha256']} for r in observed['protected']],
                'runtimeRequired': {unit: {'ActiveState': 'active'} for unit in (
                    'fs-business-range.service', 'fs-hermes-fc.service', 'nginx.service')},
                'runtimeBefore': {unit: {'ActiveState': observed['worker_state'] if unit == 'fs-hermes-fc.service' else 'active'}
                                  for unit in ('fs-business-range.service', 'fs-hermes-fc.service', 'nginx.service')},
                'workerImageSource': observed['worker_image_source'],
                'baselineObservedAt': observed['observed_at'], 'approvedPayloadSha256': payload_sha256}
    if installed:
        manifest['installedBaseline'] = INSTALLED_PROOF
        manifest['materialStaticOnly'] = all(row['beforeSha256'] == row['sha256'] or row['candidate'].startswith('frontend/')
                                            for row in files)
        if manifest['materialStaticOnly'] and (observed['worker_state'] != 'active' or observed['worker_image_source'] != 'container'):
            raise ValueError('static_followup_requires_running_worker')
    stage.mkdir(parents=True, mode=0o700)
    for name, body in bodies.items():
        path = stage / 'candidate' / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(body)
        path.chmod(0o600)
    for name in ('runtime_release.py', 'release_navigation_base.py', 'release_readiness.py'):
        shutil.copyfile(payload.parent / name, stage / name)
    raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    (stage / 'approved-manifest.json').write_bytes(raw)
    (stage / 'baseline.json').write_text(json.dumps(observed, indent=2), encoding='utf-8')
    shutil.copyfile(payload.parent / 'payload-manifest.json', stage / 'payload-manifest.json')
    return {'stage': str(stage), 'manifest_sha256': digest(raw), 'files': len(files),
            'release_ready': release_ready, 'production_writes': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('observe', 'pack', 'prepare'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--payload', type=Path)
    parser.add_argument('--source-commit')
    parser.add_argument('--approved-payload-sha256')
    parser.add_argument('--release-ready', action='store_true')
    parser.add_argument('--followup', action='store_true')
    args = parser.parse_args()
    if args.action == 'observe':
        value = observe()
    elif args.action == 'pack':
        value = pack(args.repo, args.output, args.source_commit)
    else:
        value = prepare(args.payload, args.output, args.source_commit, args.approved_payload_sha256,
                        release_ready=args.release_ready, followup=args.followup)
    print(json.dumps(value, ensure_ascii=False, indent=2))
