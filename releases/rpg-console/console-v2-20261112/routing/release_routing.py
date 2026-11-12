"""One-config adapter of the existing, SHA-pinned FS release engine.

No independent transaction/publisher: the frozen engine owns locks, durable
backup/journal, CAS, atomic replacement, automatic recovery and rollback.
Only this module's exact route payload can activate nginx; no business restart.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import types

SCOPE = 'rpg-console-route-20261112'
ENGINE = Path('/opt/fs-release-stage/traffic-source-tabs-20261019-v3/release_navigation_base.py')
ENGINE_SHA = '57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840'
TARGET = '/etc/nginx/conf.d/iggm-web.conf'
NAME = 'iggm-web.conf'
BEFORE = '359e1116ddbb5e3bb59be4b8c53065512173a2c2add49cd2ea27db7325644df7'
AFTER = '370492b9f23fa33d7edb0b049b1f17bc8997942d0a9fe71a4a77a9b3e1c523f8'
PROTECTED = {
    '/var/www/dashboard/index.html',
    '/opt/auth-portal/auth_portal.py',
    '/opt/fs-access-policy/access_policy.py',
    '/opt/fs-access-policy/rbac.py',
    '/etc/systemd/system/rpg183-link.service',
}
RUNTIME = {unit: {'ActiveState': 'active'} for unit in (
    'nginx.service', 'auth-portal.service', 'rpg183-link.service')}


def scope_guard(manifest):
    if manifest.get('scope') != SCOPE or manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:
        raise ValueError('single RPG route scope required')
    if manifest.get('runtimeRequired') != RUNTIME:
        raise ValueError('exact existing runtime boundary required')
    files = manifest.get('files', [])
    if files != [{'candidate': NAME, 'target': TARGET, 'beforeSha256': BEFORE, 'sha256': AFTER}]:
        raise ValueError('only the pinned one-file route patch is permitted')
    protected = manifest.get('unchangedRequired', [])
    if len(protected) != len(PROTECTED) or {r.get('path') for r in protected} != PROTECTED:
        raise ValueError('authorization and bridge source guards required')
    if any(not re.fullmatch('[a-f0-9]{64}', r.get('sha256', '')) for r in protected):
        raise ValueError('protected source SHA required')


def publisher(engine=ENGINE):
    raw = engine.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ENGINE_SHA:
        raise ValueError('existing frozen publisher changed')
    source = raw.decode()
    needle = '(QUERY_SCOPE,TRAFFIC_SCOPE,'
    if source.count(needle) != 2:
        raise ValueError('existing activation extension seams changed')
    # Same two dispatch seams used by the installed source-tabs adapter.
    source = source.replace(needle, '(RPG_ROUTE_SCOPE,QUERY_SCOPE,TRAFFIC_SCOPE,')
    pub = types.ModuleType('existing_rpg_route_publisher')
    pub.__file__ = str(engine)
    pub.RPG_ROUTE_SCOPE = SCOPE
    exec(compile(source, str(engine), 'exec'), pub.__dict__)
    original_validate, original_guards = pub.validate, pub.guards
    original_atomic, original_rollback = pub.atomic, pub.rollback
    pub.expected_files = lambda m: {NAME} if m.get('scope') == SCOPE else set()
    pub.target_for = lambda rel: {NAME: TARGET}[rel]

    def validate(manifest, stage):
        scope_guard(manifest)
        return original_validate(manifest, stage)

    def guards(manifest, root, reader_stopped=False):
        scope_guard(manifest)
        original_guards(manifest, root, reader_stopped)
        path = pub.rooted(root, TARGET)
        pub.no_target_link(path)
        if not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError('existing single-link regular configuration required')
        for item in (path, *path.parents):
            info = item.stat()
            if info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022:
                raise ValueError('unsafe configuration ownership or permissions')
            if item == root:
                break

    def atomic(path, data, mode=0o644):
        # Keep the engine's durable atomic writer; recheck CAS at its final
        # target-write boundary, after the engine journals its intent.
        if path.as_posix().endswith(TARGET):
            payload_sha = hashlib.sha256(data).hexdigest()
            expected = BEFORE if payload_sha == AFTER else AFTER if payload_sha == BEFORE else None
            if expected is None or pub.digest(path) != expected:
                raise ValueError('final route CAS drift; preserve later changes')
        return original_atomic(path, data, mode)

    def restart(manifest, fence=None):
        scope_guard(manifest)
        subprocess.run(['nginx', '-t'], check=True)
        subprocess.run(['systemctl', 'reload', 'nginx.service'], check=True)
        subprocess.run(['systemctl', 'is-active', '--quiet', 'nginx.service'], check=True)

    def rollback(backup, approved_sha, root=Path('/')):
        # Check scope before the engine enters its guarded rollback path.
        pub.no_target_link(backup / 'journal.json')
        scope_guard(json.loads((backup / 'journal.json').read_text())['manifest'])
        return original_rollback(backup, approved_sha, root)

    pub.validate, pub.guards = validate, guards
    pub.atomic, pub.restart_for, pub.rollback = atomic, restart, rollback
    return pub


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['inspect', 'apply', 'rollback'], nargs='?', default='inspect')
    parser.add_argument('--approved-manifest-sha')
    parser.add_argument('--release-id')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.action != 'inspect' and (os.name != 'posix' or os.geteuid() != 0):
        raise ValueError('existing authorized Linux root release identity required')
    pub = publisher()
    stage = Path(__file__).resolve().parent
    if args.action == 'rollback':
        if not args.backup or args.backup.parent != Path('/var/backups/fs-navigation-20261006') or not re.fullmatch(r'nav-[0-9]{8}T[0-9]{6}Z', args.backup.name):
            raise ValueError('exact existing publisher backup path required')
        result = pub.rollback(args.backup, args.approved_manifest_sha)
    else:
        raw = (stage / 'manifest.json').read_bytes()
        manifest = json.loads(raw)
        result = pub.inspect(manifest, stage) if args.action == 'inspect' else pub.apply(manifest, stage, args.approved_manifest_sha, raw, args.release_id)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
