"""Publish the one-line VIP GET paging limit through the original Range-only release lane."""
import json
import subprocess
import sys
import types
from pathlib import Path
from zipfile import ZipFile

from vip_release import (BASE_REPO, BASE_SHA, HERE, RELEASE, checked_file, encoded,
                         path_in, sha, tracking_quiescent, version)


SCOPE = 'hermes-vip-paging-20261120'
NAME = 'source/range_api.py'
TARGET = '/opt/fs-exact-range-20261001/range_api.py'
BEFORE = '604c242f50e30de5704d2924df0e8e03b3d870026233c833fc4dff9cf73872c9'
PATCH = 'vip_paging_patch.py'
PROTECTED = {
    '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf',
    '/etc/systemd/system/fs-business-range.service',
    '/var/www/dashboard/index.html',
    *('/opt/fs-hermes-fc/' + name for name in (
        'tracking_controller.py', 'vip_query.py', 'vip_followup.py', 'vip_maintenance.py')),
}
RUNTIME = {'fs-business-range.service': {'ActiveState': 'active'}}


def bundle(repo, output, commit):
    commit = version(commit)

    def blob(path):
        return subprocess.check_output(['git', '-C', str(repo), 'cat-file', 'blob', f'{commit}:{path}'])

    base, patch = blob(BASE_REPO), blob(RELEASE + '/source/' + PATCH)
    if sha(base) != BASE_SHA:
        raise ValueError('vip_paging_publisher_drift')
    with ZipFile(output, 'x') as archive:
        for name in ('vip_release.py', 'vip_paging_release.py'):
            archive.writestr(name, blob(RELEASE + '/deploy/' + name))
        archive.writestr('release_navigation_base.py', base)
        archive.writestr(PATCH, patch)
        archive.writestr('source-proof.json', encoded(dict(sourceCommit=commit, patchSha256=sha(patch))))
    return dict(sourceCommit=commit, payloads=1, archiveSha256=sha(Path(output).read_bytes()))


def source_proof(stage):
    proof = json.loads((stage / 'source-proof.json').read_bytes())
    version(proof['sourceCommit'])
    patch = checked_file(stage / PATCH).read_bytes()
    if sha(patch) != proof['patchSha256']:
        raise ValueError('vip_paging_patch_drift')
    return proof, patch


def prepare(stage, root=Path('/')):
    proof, patch = source_proof(stage)
    current = checked_file(path_in(root, TARGET)).read_bytes()
    if sha(current) != BEFORE:
        raise ValueError('vip_paging_live_baseline_drift')
    module = types.ModuleType('vip_paging_frozen_patch')
    exec(compile(patch, str(stage / PATCH), 'exec'), module.__dict__)
    candidate = module.patch(current)
    if len(candidate) != len(current) or sum(a != b for a, b in zip(current, candidate)) != 1:
        raise ValueError('vip_paging_exact_single_byte_change_required')
    compile(candidate, TARGET, 'exec')
    file = stage / 'candidate' / NAME
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open('xb') as out:
        out.write(candidate)
    manifest = dict(schemaVersion=1, scope=SCOPE, releaseReady=True, sourceCommit=proof['sourceCommit'],
                    businessWrites=False, timersChanged=False, runtimeRequired=RUNTIME,
                    files=[dict(candidate=NAME, target=TARGET, beforeSha256=BEFORE, sha256=sha(candidate))],
                    unchangedRequired=[dict(path=path, sha256=sha(checked_file(path_in(root, path)).read_bytes()))
                                       for path in sorted(PROTECTED)])
    raw = encoded(manifest)
    with (stage / 'approved-manifest.json').open('xb') as out:
        out.write(raw)
    return dict(sourceCommit=proof['sourceCommit'], payloads=1, protected=len(PROTECTED),
                manifestSha256=sha(raw), beforeSha256=BEFORE, afterSha256=sha(candidate))


def publisher(stage=HERE):
    raw = (stage / 'release_navigation_base.py').read_bytes()
    if sha(raw) != BASE_SHA:
        raise ValueError('vip_paging_publisher_drift')
    base = types.ModuleType('vip_paging_frozen_publisher')
    base.__file__ = str(stage / 'release_navigation_base.py')
    exec(compile(raw, base.__file__, 'exec'), base.__dict__)
    # The frozen publisher restarts only Range for DEEP and retains its source/model locks.
    base.DEEP_SCOPE = SCOPE
    base.expected_files = lambda manifest: {NAME} if manifest.get('scope') == SCOPE else set()
    base.target_for = {NAME: TARGET}.__getitem__
    approved = json.loads((stage / 'approved-manifest.json').read_bytes())
    guards_original = base.guards

    def validate(manifest, candidate_stage):
        proof, _ = source_proof(candidate_stage)
        candidate = checked_file(candidate_stage / 'candidate' / NAME)
        row = dict(candidate=NAME, target=TARGET, beforeSha256=BEFORE, sha256=sha(candidate.read_bytes()))
        if (manifest != approved or manifest.get('scope') != SCOPE or manifest.get('schemaVersion') != 1
                or manifest.get('sourceCommit') != proof['sourceCommit'] or manifest.get('files') != [row]
                or manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False
                or manifest.get('runtimeRequired') != RUNTIME
                or {entry['path'] for entry in manifest['unchangedRequired']} != PROTECTED):
            raise ValueError('vip_paging_exact_release_scope_required')
        return manifest['files']

    def guards(manifest, root, **kwargs):
        guards_original(dict(manifest, scope='vip-paging-runtime'), root, **kwargs)
        target = checked_file(path_in(root, TARGET))
        for path in (target, *target.parents):
            info = path.stat()
            if info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022 or path == target and info.st_nlink != 1:
                raise ValueError('vip_paging_unsafe_target_permissions')
            if path == root:
                break
        tracking_quiescent(base, root)

    base.validate, base.guards = validate, guards
    return base


def main(action, *args):
    if action == 'bundle' and len(args) == 3:
        result = bundle(Path(args[0]), Path(args[1]), args[2])
    elif action == 'prepare' and not args:
        result = prepare(HERE)
    else:
        publisher().main()
        return
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main(*sys.argv[1:])
