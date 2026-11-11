"""Exact email-export scope over the frozen navigation writer; no transport/shell."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import types

BASE = Path('/opt/fs-release-stage/data-tools-query-fix-ui-20261018-v1/release_navigation_base.py')
BASE_SHA256 = '5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357'
SCOPE = 'order-email-export-20261111'
STATIC = '/var/lib/fs-navigation-formal-static/workspace-native-20261006-4f4a56f7a335/'
NGINX = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
TARGETS = {
    'formal.locations.conf': NGINX,
    'range_api.py': '/opt/fs-exact-range-20261001/range_api.py',
    'admin_order_email_export.py': '/opt/fs-hermes-fc/admin_order_email_export.py',
    **{name: STATIC + name for name in ('page.js', 'data-workspace.js', 'order-email-panel.js',
                                       'order-email-run.js', 'order-email-csv.js', 'order-email-xlsx.js')},
}
PENDING = '/var/backups/fs-navigation-native-20261006/pending.json'
PROTECTED = {
    '/opt/fs-hermes-fc/controller.py',
    '/opt/fs-exact-range-20261001/fc_daily.py',
    '/opt/fs-hermes-fc/admin_live_admission.py',
    '/opt/fs-hermes-fc/cache_retention.py',
    '/etc/systemd/system/fs-business-range.service',
}
RUNTIME = {'fs-business-range.service': {'ActiveState': 'active'}}
HASH = re.compile(r'[a-f0-9]{64}')


def contract(manifest):
    allowed = {'schemaVersion', 'scope', 'releaseReady', 'businessWrites', 'timersChanged',
               'files', 'unchangedRequired', 'runtimeRequired', 'sourceCommit'}
    if set(manifest) - allowed or manifest.get('scope') != SCOPE or manifest.get('schemaVersion') != 1:
        raise ValueError('exact email-export manifest required')
    if manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:
        raise ValueError('readonly business and unchanged timers required')
    if manifest.get('runtimeRequired') != RUNTIME:
        raise ValueError('only active range runtime contract allowed')
    if not re.fullmatch(r'[a-f0-9]{40}', manifest.get('sourceCommit', '')):
        raise ValueError('exact source commit required')
    files = manifest.get('files', [])
    if len(files) != len(TARGETS) or {r.get('candidate') for r in files} != set(TARGETS):
        raise ValueError('exact nine targets required; tools-index.html is not in this scope')
    for row in files:
        if set(row) != {'candidate', 'target', 'sha256', 'beforeSha256'}:
            raise ValueError('exact file row required')
        if row['target'] != TARGETS[row['candidate']] or not HASH.fullmatch(row['sha256'] or ''):
            raise ValueError('invalid target or payload hash')
        before = row['beforeSha256']
        if before is not None and not HASH.fullmatch(before):
            raise ValueError('invalid before CAS')
        if row['candidate'] in ('formal.locations.conf', 'range_api.py', 'page.js', 'data-workspace.js') and before is None:
            raise ValueError('existing source requires non-null CAS')
    protected = manifest.get('unchangedRequired', [])
    paths = [r.get('path') for r in protected]
    if len(paths) != len(set(paths)) or set(paths) != PROTECTED:
        raise ValueError('protected dependency set differs')
    for row in protected:
        path = row.get('path', '')
        if set(row) != {'path', 'sha256'} or not path.startswith('/') or str(Path(path).as_posix()) != path or '..' in path.split('/') or not HASH.fullmatch(row.get('sha256') or ''):
            raise ValueError('invalid protected source')
    return files


def pending_guard(base, root):
    path = base.rooted(root, PENDING)
    base.no_target_link(path)
    if path.exists():
        raise ValueError('native pending release must be reconciled first')


def adapt(base):
    """Patch only an isolated, hash-verified module, never the installed writer."""
    original_guards = base.guards
    original_fence = base.hermes_admission_fence
    original_restart = base.restart_for
    # This existing branch already journals apply/failure restore and range-only restart.
    base.DEEP_SCOPE = SCOPE
    base.expected_files = lambda manifest: {r['candidate'] for r in contract(manifest)}
    base.target_for = lambda name: TARGETS[name]

    def validate(manifest, stage):
        files = contract(manifest)
        stage = Path(stage)
        for row in files:
            source = stage / 'candidate' / row['candidate']
            base.no_target_link(source)
            if (stage / 'candidate').resolve() not in source.resolve().parents or base.digest(source) != row['sha256']:
                raise ValueError('staged payload differs')
        return files

    def guards(manifest, root):
        contract(manifest)
        pending_guard(base, root)
        for target in list(TARGETS.values()) + [r['path'] for r in manifest['unchangedRequired']]:
            path = base.rooted(root, target)
            base.no_target_link(path)
            for item in (path, *path.parents):
                if item.exists():
                    info = item.stat()
                    if info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o022 or (item.is_file() and info.st_nlink != 1):
                        raise ValueError('unsafe source ownership/mode/link count')
                if item == root:
                    break
        # Only the original generic runtime/protected-CAS checks, not historical scopes.
        original_guards(dict(manifest, scope='email-export-generic-guards'), root)

    @contextlib.contextmanager
    def fence(manifest, root):
        contract(manifest)
        pending_guard(base, root)
        with original_fence(dict(manifest, scope=base.HERMES_UPDATE_SCOPE), root) as held:
            yield held

    def restart(manifest, admission_fence=None):
        contract(manifest)
        if admission_fence is None:
            raise ValueError('range restart requires original Hermes admission fence')
        # A bad static route rolls back before touching the running range process.
        base.subprocess.run(['nginx', '-t'], check=True, timeout=30)
        admission_fence.stop_then_unlock_database()
        original_restart(manifest, admission_fence)
        base.subprocess.run(['systemctl', 'reload', 'nginx'], check=True, timeout=30)
        base.subprocess.run(['systemctl', 'is-active', '--quiet', 'nginx'], check=True, timeout=15)

    base.validate = validate
    base.guards = guards
    base.retirement = lambda root: pending_guard(base, root)
    base.hermes_admission_fence = fence
    base.restart_for = restart
    return base


def load_base():
    if BASE.is_symlink() or any(p.is_symlink() for p in BASE.parents):
        raise ValueError('linked base writer')
    raw = BASE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA256:
        raise ValueError('frozen base writer SHA differs')
    module = types.ModuleType('_email_export_frozen_writer')
    module.__file__ = str(BASE)
    exec(compile(raw, str(BASE), 'exec'), module.__dict__)
    return adapt(module)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('plan', 'inspect', 'apply', 'rollback'), nargs='?', default='plan')
    parser.add_argument('--manifest', type=Path, default=Path(__file__).with_name('approved-manifest.json'))
    parser.add_argument('--approved-manifest-sha')
    parser.add_argument('--release-id')
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    base = load_base()
    if args.action in ('apply', 'rollback') and os.name != 'posix':
        raise ValueError('mutation requires Linux writer environment')
    if args.action == 'rollback':
        if args.backup is None or args.backup.parent != Path('/var/backups/fs-navigation-20261006') or not re.fullmatch(r'nav-[0-9]{8}T[0-9]{6}Z', args.backup.name):
            raise ValueError('exact original writer backup required')
        pending_guard(base, Path('/'))
        result = base.rollback(args.backup, args.approved_manifest_sha)
    else:
        raw = args.manifest.read_bytes()
        manifest = json.loads(raw)
        contract(manifest)
        if args.action == 'plan':
            base.validate(manifest, args.manifest.parent)
            result = {'scope': SCOPE, 'mutations': False, 'manifestSha256': hashlib.sha256(raw).hexdigest(), 'targets': TARGETS}
        elif args.action == 'inspect':
            result = base.inspect(manifest, args.manifest.parent)
        else:
            if not HASH.fullmatch(args.approved_manifest_sha or '') or hashlib.sha256(raw).hexdigest() != args.approved_manifest_sha:
                raise ValueError('apply requires exact manifest SHA')
            result = base.apply(manifest, args.manifest.parent, args.approved_manifest_sha, raw, args.release_id)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
