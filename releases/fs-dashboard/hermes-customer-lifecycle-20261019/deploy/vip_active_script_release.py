"""Publish the VIP script to the exact active Nginx alias through the original UI publisher."""
import json
import re
import stat
import subprocess
import sys
import types
from pathlib import Path
from zipfile import ZipFile

from vip_release import BASE_REPO, BASE_SHA, HERE, RELEASE, RUNTIME, checked_file, encoded, path_in, sha, version


SCOPE = 'hermes-vip-active-script-20261120'
ROUTE = '/dashboard/fs-home/hermes/customer-tracking/page.js'
CONFIG = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
NAME = 'source/tracking-page.js'
TARGET = '/var/lib/fs-navigation-formal-static/workspace-native-20261006-4f4a56f7a335/tracking-page.js'
BEFORE = '856f84db0c2f8263237fe4b2e684403c9eeec2dba96a03c254d2d4bb11854c2b'
PREVIOUS = '/opt/fs-release-stage/hermes-vip-maintenance-20261120-c56c0af64bfa/approved-manifest.json'
PREVIOUS_SHA = '1c68f8fdc26717da059ee4720e690b0c54ed3418b4bb3eb33c56533c5c2ca6f5'
HOME = '/var/www/dashboard/index.html'


def check_route(text):
    blocks = re.findall(r'^location = ' + re.escape(ROUTE) + r' \{\n(.*?)^\}', text, re.MULTILINE | re.DOTALL)
    if len(blocks) != 1:
        raise ValueError('vip_active_route_drift')
    aliases = re.findall(r'^\s*alias ([^;]+);', blocks[0], re.MULTILINE)
    if aliases != [TARGET] or 'auth_request /__nav_formal_native_session;' not in blocks[0]:
        raise ValueError('vip_active_alias_or_guard_drift')


def checked_target(root):
    path = checked_file(path_in(root, TARGET))
    info = path.stat()
    if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink) != (0, 0, 0o644, 1):
        raise ValueError('vip_active_target_owner_mode_drift')
    return path


def checked_proof(stage):
    proof = json.loads((stage / 'source-proof.json').read_bytes())
    version(proof['sourceCommit'])
    source = checked_file(stage / 'candidate' / NAME).read_bytes()
    if sha(source) != proof['sha256'] or proof['sha256'] == BEFORE:
        raise ValueError('vip_active_source_drift')
    return proof


def bundle(repo, output, commit):
    commit = version(commit)

    def blob(path):
        return subprocess.check_output(['git', '-C', str(repo), 'cat-file', 'blob', f'{commit}:{path}'])

    base, asset = blob(BASE_REPO), blob(RELEASE + '/frontend/page.js')
    if sha(base) != BASE_SHA or sha(blob('releases/fs-dashboard/fs-business-baseline-20261021/source/ui/tracking-page.js')) != BEFORE:
        raise ValueError('vip_active_source_baseline_drift')
    with ZipFile(output, 'x') as archive:
        for name in ('vip_release.py', 'vip_active_script_release.py'):
            archive.writestr(name, blob(RELEASE + '/deploy/' + name))
        archive.writestr('release_navigation_base.py', base)
        archive.writestr('source-proof.json', encoded(dict(sourceCommit=commit, sha256=sha(asset))))
        archive.writestr('candidate/' + NAME, asset)
    return dict(sourceCommit=commit, payloads=1, archiveSha256=sha(Path(output).read_bytes()))


def prepare(stage, root=Path('/')):
    proof = checked_proof(stage)
    config = checked_file(path_in(root, CONFIG))
    check_route(config.read_text(encoding='utf-8'))
    if sha(checked_target(root).read_bytes()) != BEFORE:
        raise ValueError('vip_active_target_baseline_drift')
    previous = checked_file(path_in(root, PREVIOUS)).read_bytes()
    if sha(previous) != PREVIOUS_SHA:
        raise ValueError('vip_previous_release_manifest_drift')
    protected = {row['target']: row['sha256'] for row in json.loads(previous)['files']}
    if any(sha(checked_file(path_in(root, path)).read_bytes()) != digest for path, digest in protected.items()):
        raise ValueError('vip_previous_release_target_drift')
    for name in (CONFIG, HOME):
        protected[name] = sha(checked_file(path_in(root, name)).read_bytes())
    row = dict(candidate=NAME, target=TARGET, beforeSha256=BEFORE, sha256=proof['sha256'], owner='0:0', mode='0o644')
    manifest = dict(schemaVersion=1, scope=SCOPE, releaseReady=True, sourceCommit=proof['sourceCommit'],
                    businessWrites=False, timersChanged=False, runtimeRequired=RUNTIME, files=[row],
                    unchangedRequired=[dict(path=name, sha256=digest) for name, digest in sorted(protected.items())])
    payload = encoded(manifest)
    with (stage / 'approved-manifest.json').open('xb') as out:
        out.write(payload)
    return dict(sourceCommit=proof['sourceCommit'], payloads=1, protected=len(protected), manifestSha256=sha(payload))


def publisher(stage=HERE):
    raw = (stage / 'release_navigation_base.py').read_bytes()
    if sha(raw) != BASE_SHA:
        raise ValueError('vip_active_frozen_publisher_drift')
    base = types.ModuleType('vip_active_frozen_publisher')
    base.__file__ = str(stage / 'release_navigation_base.py')
    exec(compile(raw, base.__file__, 'exec'), base.__dict__)
    base.expected_files = lambda manifest: {NAME} if manifest.get('scope') == SCOPE else set()
    base.target_for = {NAME: TARGET}.__getitem__
    approved = json.loads((stage / 'approved-manifest.json').read_bytes())
    validate_original, guards_original = base.validate, base.guards

    def validate(manifest, candidate_stage):
        proof = checked_proof(candidate_stage)
        row = dict(candidate=NAME, target=TARGET, beforeSha256=BEFORE, sha256=proof['sha256'], owner='0:0', mode='0o644')
        if (manifest != approved or manifest.get('scope') != SCOPE or manifest['files'] != [row]
                or manifest.get('sourceCommit') != proof['sourceCommit'] or manifest.get('businessWrites') is not False
                or manifest.get('timersChanged') is not False or manifest.get('runtimeRequired') != RUNTIME):
            raise ValueError('vip_active_scope_drift')
        return validate_original(manifest, candidate_stage)

    def guards(manifest, root, **kwargs):
        guards_original(manifest, root, **kwargs)
        check_route(checked_file(path_in(root, CONFIG)).read_text(encoding='utf-8'))
        checked_target(root)

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
