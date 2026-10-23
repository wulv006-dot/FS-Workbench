"""Native-only scope adapter over the original publisher: locks, CAS, backup and journal stay there."""
from contextlib import closing, contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import subprocess

HERE = Path(__file__).resolve().parent
SCOPE = 'knowledge-native-fs-20261023'
PLUGIN = '/var/lib/fs-hermes-fc/profile/plugins/fs-readonly/'
TARGETS = {'plugin/__init__.py': PLUGIN + '__init__.py', 'plugin/knowledge.py': PLUGIN + 'knowledge.py',
           'policy/knowledge-load-policy.json': '/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json',
           'native/desktop.service': '/etc/systemd/system/fs-hermes-desktop.service'}
UNITS = ('fs-hermes-desktop.service', 'hermes-dingtalk.service')
IMAGE = re.compile(r'sha256:[a-f0-9]{64}')


def original_plugin_sha(raw):
    addition = b'    from .knowledge import register as register_knowledge\n    register_knowledge(ctx)\n'
    if raw.count(addition) != 1:
        raise ValueError('native_plugin_exact_registration_delta_required')
    return hashlib.sha256(raw.replace(addition, b'', 1)).hexdigest()


def checked(manifest, stage=None):
    if (manifest.get('scope') != SCOPE or len(manifest.get('files', [])) != len(TARGETS)
            or {r['candidate']: r['target'] for r in manifest['files']} != TARGETS
            or manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False
            or manifest.get('nativeUnits') != list(UNITS)):
        raise ValueError('native_exact_scope_required')
    checked_sqlite_version(manifest.get('nativeSQLiteVersion'))
    for key in ('nativeImageBefore', 'nativeImageAfter'):
        if not IMAGE.fullmatch(manifest.get(key, '')):
            raise ValueError('native_pinned_image_required')
    if manifest['nativeImageBefore'] == manifest['nativeImageAfter']:
        raise ValueError('native_image_must_include_constructor_patch')
    if set(manifest.get('nativeImageSources', {})) != {'/opt/hermes/tui_gateway/server.py', '/opt/hermes/fs_native_entry.py'} or any(
            not re.fullmatch('[a-f0-9]{64}', sha) for sha in manifest['nativeImageSources'].values()):
        raise ValueError('native_image_exact_sources_required')
    if stage is not None:
        plugin = next(r for r in manifest['files'] if r['candidate'] == 'plugin/__init__.py')
        if original_plugin_sha((Path(stage) / 'candidate/plugin/__init__.py').read_bytes()) != plugin['beforeSha256']:
            raise ValueError('native_original_tools_source_drift')
        row = next(r for r in manifest['files'] if r['candidate'] == 'native/desktop.service')
        raw = (Path(stage) / 'candidate/native/desktop.service').read_bytes()
        after, before = (manifest[k].encode() for k in ('nativeImageAfter', 'nativeImageBefore'))
        if raw.count(after) != 1 or hashlib.sha256(raw.replace(after, before)).hexdigest() != row['beforeSha256']:
            raise ValueError('native_unit_only_image_substitution_allowed')
        row = next(r for r in manifest['files'] if r['candidate'].startswith('policy/'))
        value = json.loads((Path(stage) / 'candidate' / row['candidate']).read_bytes())
        preserved = {k: v for k, v in value.items() if k != 'native'}
        if hashlib.sha256(json.dumps(preserved, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != manifest.get('policyPreservedSha256'):
            raise ValueError('native_policy_existing_requests_changed')
    return manifest


def native_database(root):
    return Path(root) / 'var/lib/fs-hermes-fc/profile/state.db'


def checked_sqlite_version(version):
    # WITHOUT ROWID is a necessary floor, not proof that the whole native schema is readable.
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version) or tuple(map(int, version.split('.'))) < (3, 8, 2):
        raise ValueError('native_sqlite_compatible_pinned_version_required')
    return version


def verify_sqlite_runtime(version):
    checked_sqlite_version(version)
    if sqlite3.sqlite_version != version:
        raise ValueError('native_sqlite_runtime_drift: expected=' + version + ' actual=' + sqlite3.sqlite_version)
    with closing(sqlite3.connect(':memory:')) as db:
        db.execute("CREATE TABLE messages_fts_trigram_config(k PRIMARY KEY, v) WITHOUT ROWID")


def probe_native_database(base, root, version):
    verify_sqlite_runtime(version)
    path = native_database(root)
    base.no_target_link(path)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('SELECT conversation_id, holder, acquired_at, expires_at FROM session_turn_leases LIMIT 0')


def acquire_native_database(base, root, version):
    verify_sqlite_runtime(version)
    path = native_database(root)
    base.no_target_link(path)
    connection = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=0)
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('SELECT conversation_id, holder, acquired_at, expires_at FROM session_turn_leases LIMIT 0')
        # Even expired rows remain unresolved evidence; never reclaim another turn here.
        if connection.execute('SELECT count(*) FROM session_turn_leases').fetchone()[0]:
            raise ValueError('native_turn_active_or_unreconciled')
        return connection
    except Exception:
        connection.close()
        raise


def install_native_scope(base, approved):
    version = checked_sqlite_version(approved.get('nativeSQLiteVersion'))
    class NativeFence(base.HermesAdmissionFence):
        def __init__(self, root):
            self.native_db = None
            super().__init__(root)
            try:
                self.native_db = acquire_native_database(base, root, version)
            except Exception:
                self.close()
                raise

        def unlock_native(self):
            if self.native_db is not None:
                self.native_db.rollback()
                self.native_db.close()
                self.native_db = None

        def close(self):
            self.unlock_native()
            super().close()

    active = [None]

    @contextmanager
    def fence(manifest, root):
        if manifest.get('nativeSQLiteVersion') != version:
            raise ValueError('native_sqlite_approved_version_changed')
        current = NativeFence(root)
        active[0] = current
        try:
            yield current
        finally:
            active[0] = None
            current.close()  # Never invoke the business-range stop helper.

    def stop_native(current):
        if current.native_db is None:
            current.native_db = acquire_native_database(base, current.root, version)
        subprocess.run(['systemctl', 'stop', *reversed(UNITS)], check=True, timeout=45)
        for unit in UNITS:
            output = subprocess.check_output(['systemctl', 'show', unit, '--no-pager', '-p', 'ActiveState'], text=True)
            state = dict(line.split('=', 1) for line in output.splitlines() if '=' in line).get('ActiveState')
            if state not in ('inactive', 'failed'):
                raise ValueError('native_stop_outcome_unknown')
        current.unlock_native()

    restore = base.rollback_journal

    def restart_native(manifest, admission_fence=None):
        if admission_fence is None:
            raise ValueError('native_admission_fence_required')
        # Files and image-only unit are all verified before admitting the new native process.
        stop_native(admission_fence)
        subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=20)
        subprocess.run(['systemctl', 'start', *UNITS], check=True, timeout=60)
        for unit in UNITS:
            subprocess.run(['systemctl', 'is-active', '--quiet', unit], check=True, timeout=10)
        raw = base.rooted(admission_fence.root, TARGETS['native/desktop.service']).read_bytes()
        expected = [manifest[k] for k in ('nativeImageBefore', 'nativeImageAfter') if manifest[k].encode() in raw]
        actual = subprocess.check_output(['docker', 'inspect', '-f', '{{.Image}}', 'fs-hermes-desktop'], text=True).strip()
        if len(expected) != 1 or actual != expected[0]:
            raise ValueError('native_running_image_readback_differs')

    def restore_native(backup, journal, root):
        current = active[0]
        if current is None:
            raise ValueError('native_rollback_fence_required')
        try:
            stop_native(current)
        except Exception:
            journal['status'] = 'unknown-needs-reconcile'
            base.journal_write(backup, journal)
            raise
        restore(backup, journal, root)

    base.hermes_admission_fence = fence
    base.restart_for = restart_native
    base.rollback_journal = restore_native
    return base


def load_base():
    raw = (HERE / 'release_adapter_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != '6ed1c826b8b4464fc81e29e236ea9f81fedf82e65f3e80aab6cb385abcd1c141':
        raise ValueError('existing_adapter_drift')
    approved = checked(json.loads((HERE / 'approved-manifest.json').read_text('utf-8')), HERE)
    spec = importlib.util.spec_from_file_location('existing_native_scope', HERE / 'release_adapter_base.py')
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    adapter.HERE, adapter.SCOPE, adapter.TARGETS = HERE, SCOPE, TARGETS
    adapter.AUTHORIZED_TIMERS = frozenset()
    adapter.NEW = frozenset(r['candidate'] for r in approved['files'] if r['beforeSha256'] is None)
    if not adapter.NEW <= {'plugin/knowledge.py', 'policy/knowledge-load-policy.json'}:
        raise ValueError('native_new_file_boundary')
    base = adapter.load_base()
    validate = base.validate

    def validate_native(manifest, stage):
        checked(manifest, stage)
        return validate(manifest, stage)

    base.validate = validate_native
    inspect = base.inspect

    def inspect_native(manifest, stage, root=Path('/')):
        probe_native_database(base, root, manifest['nativeSQLiteVersion'])
        policy = base.rooted(root, TARGETS['policy/knowledge-load-policy.json'])
        current = json.loads(policy.read_bytes()) if policy.exists() else {'contract': 'fs-knowledge-load-policy-v1', 'requests': {}}
        preserved = {k: v for k, v in current.items() if k != 'native'}
        if hashlib.sha256(json.dumps(preserved, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != manifest['policyPreservedSha256']:
            raise ValueError('native_policy_current_non_native_drift')
        actual = subprocess.check_output(['docker', 'inspect', '-f', '{{.Image}}', 'fs-hermes-desktop'], text=True).strip()
        if actual != manifest['nativeImageBefore']:
            raise ValueError('native_running_image_baseline_drift')
        result = subprocess.check_output(['docker', 'run', '--rm', '--read-only', '--network', 'none',
                                          '--entrypoint', 'sha256sum', manifest['nativeImageAfter'],
                                          *sorted(manifest['nativeImageSources'])], text=True)
        if {line.split()[1]: line.split()[0] for line in result.splitlines()} != manifest['nativeImageSources']:
            raise ValueError('native_built_image_sources_differ')
        return inspect(manifest, stage, root)

    base.inspect = inspect_native
    return install_native_scope(base, approved)


if __name__ == '__main__':
    load_base().main()
