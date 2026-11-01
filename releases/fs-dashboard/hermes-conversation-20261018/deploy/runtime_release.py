"""Exact material-files adapter over the original publisher, not a new writer."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import types

HERE = Path(__file__).resolve().parent
SCOPE = 'hermes-materials-runtime-20261101'
BASE_SHA = '1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de'
FROZEN_IMAGE_MARKER = 'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'
NGINX = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
TARGETS = {'runtime/' + name: '/opt/fs-hermes-fc/' + name for name in (
    'conversation_store.py', 'conversation_files.py', 'conversation_file_bindings.py',
    'conversation_service.py', 'conversation_file_tools.py', 'material_evidence.py',
    'runs_contract.py', 'proxy_gateway.py', 'hermes_worker.py')}
TARGETS.update({'http/conversation_http.py': '/opt/fs-exact-range-20261001/conversation_http.py',
                'http/formal.conf': NGINX})
TARGETS.update({'frontend/' + name: '/var/www/dashboard/fs-home/hermes/conversation/' + name
                for name in ('index.html', 'conversation.js', 'conversation.css')})
NEW = frozenset('runtime/' + name for name in (
    'conversation_files.py', 'conversation_file_bindings.py',
    'conversation_file_tools.py', 'material_evidence.py'))
INSTALLED_COMMIT = '1f8ddc57c37e16df7c802de358eefb6585d078ee'
INSTALLED_PROOF = {
    'sourceCommit': INSTALLED_COMMIT,
    'backup': '/var/backups/fs-navigation-20261006/nav-20261031T192312Z',
    'manifestSha256': 'b129179049dc9ff4b575075ebd1b47c1f6edf325936ac70b1286ca990bd73a05',
    'journalSha256': 'c902e8f3d1d613c80f1f0573647dbcf17184466579fdfbc77539d8f8846c24fc'}
INSTALLED_NGINX_SHA = 'b792f18b8d1b322139f8be96bb5052ff53a79e82dac7a607cbe102e199b06302'
LEGACY_TARGETS = dict(TARGETS)
EXECUTION_MODE = False
DIAGNOSTICS_MODE = False
EXECUTION_MODULES = ('conversation_goals.py','conversation_goal_tasks.py','conversation_material_runs.py',
                     'material_execution.py','b2_goal_state.py','b2_goal_host.py','b1_model_routing.py','b2_customer_followup.py')


def configure_execution():
    """Same publisher, explicit 501f installed-baseline increment; never a replay."""
    global INSTALLED_COMMIT, NEW, EXECUTION_MODE
    if EXECUTION_MODE:
        return
    EXECUTION_MODE = True
    INSTALLED_COMMIT = '501f90bf16fe114e70fcb05833cb1b2cf478e54c'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261031T201743Z',
        manifestSha256='6c6c1aceda92eba62cb694f112dc6df93f97dd05fc157c778b51c4ffe8daf920',
        journalSha256='9131be81c7c95da5c15a0c6ba49107102517952f009046e524dd813c1732c9b9')
    TARGETS.update({'runtime/'+name:'/opt/fs-hermes-fc/'+name for name in EXECUTION_MODULES})
    TARGETS.update({'runtime/fs_inprocess.py':'/opt/fs-hermes-fc/fs_inprocess.py',
                    'http/range_api.py':'/opt/fs-exact-range-20261001/range_api.py'})
    NEW = frozenset('runtime/'+name for name in EXECUTION_MODULES)


def configure_diagnostics():
    """Exact 5f99 follow-up: all 24 targets already exist, including NEW8."""
    global INSTALLED_COMMIT, NEW, DIAGNOSTICS_MODE
    if DIAGNOSTICS_MODE:
        return
    configure_execution()
    DIAGNOSTICS_MODE = True
    INSTALLED_COMMIT = '5f99f5b3eeca8bdf974de1dcd913508ff4c89c1f'
    INSTALLED_PROOF.update(sourceCommit=INSTALLED_COMMIT,
        backup='/var/backups/fs-navigation-20261006/nav-20261101T013519Z',
        manifestSha256='4057435dce473622c5ef2f88ba0d55255a9f7b588a6e193f70a41cffca409881',
        journalSha256='3f6d474d37716610de334f14b9b7a699f879aae170471c065f5007c47e3ab93d')
    NEW = frozenset()


def installed_baseline(root, git_baseline):
    """Bind an installed baseline to both the successful journal and Git bytes."""
    base = frozen()
    records = {}
    for name, key in (('approved-manifest.json', 'manifestSha256'), ('journal.json', 'journalSha256')):
        path = base.rooted(root, INSTALLED_PROOF['backup'] + '/' + name)
        base.no_target_link(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != INSTALLED_PROOF[key]:
            raise ValueError('installed_release_proof_drift')
        records[name] = json.loads(raw)
    manifest, journal = records['approved-manifest.json'], records['journal.json']
    expected = {row['candidate']: row['sha256'] for row in manifest['files']}
    proof_targets = LEGACY_TARGETS if EXECUTION_MODE and not DIAGNOSTICS_MODE else TARGETS
    if EXECUTION_MODE and not DIAGNOSTICS_MODE:
        protected = {r['path']:r['sha256'] for r in manifest['unchangedRequired']}
        expected.update({name: None if name in NEW else protected[target]
                         for name,target in TARGETS.items() if name not in LEGACY_TARGETS})
    if (manifest.get('sourceCommit') != INSTALLED_COMMIT or manifest.get('scope') != SCOPE
            or {row['candidate']: row['target'] for row in manifest['files']} != proof_targets
            or journal.get('status') != 'applied-awaiting-actual-http-role-acceptance'
            or journal.get('approvedManifestSha256') != INSTALLED_PROOF['manifestSha256']
            or journal.get('manifest') != manifest
            or git_baseline != {'source_commit': INSTALLED_COMMIT, 'files': expected}):
        raise ValueError('installed_git_and_journal_mismatch')
    return manifest


def frozen():
    raw = (HERE / 'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise ValueError('frozen_publisher_drift')
    source = raw.decode('utf-8')
    anchor = "r.get('beforeSha256') is None for r in files if not ("
    if source.count(anchor) != 1:
        raise ValueError('frozen_new_file_anchor_drift')
    source = source.replace(anchor, "r.get('beforeSha256') is None for r in files if r['candidate'] not in MATERIAL_NEW if not (", 1)
    base = types.ModuleType('original_material_publisher')
    base.__file__ = str(HERE / 'release_navigation_base.py')
    base.MATERIAL_NEW = NEW
    exec(compile(source, base.__file__, 'exec'), base.__dict__)
    base.HERMES_HISTORY_SCOPE, base.HERMES_HISTORY_TARGETS = SCOPE, TARGETS
    base.expected_files = lambda manifest: set(TARGETS) if manifest.get('scope') == SCOPE else set()
    base.target_for = lambda name: TARGETS[name]
    return base


def protected_paths(base):
    # Preserve the original publisher's required consumers, plus this package's
    # unchanged live host/seams. No DB, credential or model-key payload is copied.
    paths = set(base.HERMES_TARGETS.values()) | {
        '/opt/fs-exact-range-20261001/' + name for name in (
            'boss_insights.py', 'fc_deep_model.py', 'fc_daily.py', 'fc_daily_model.py',
            'fc_detail.py', 'fc_detail_model.py', 'fc_detail_reader.py',
            'fc_detail_config.json', 'fc_deep_sources.py', 'summary_bridge.py')}
    paths.update(('/var/www/dashboard/index.html', '/var/www/dashboard/fs-home/index.html',
                  '/var/www/dashboard/fs-home/navigation.js', '/opt/fs-access-policy/access_policy.py',
                  '/opt/fs-hermes-fc/direct_provider.py', '/etc/systemd/system/fs-business-range.service',
                  '/etc/systemd/system/fs-hermes-fc.service.d/install-state-isolation.conf'))
    return paths - set(TARGETS.values())


def worker_observation(*, allow_stopped=False):
    checked = subprocess.run(['docker', 'inspect', '--format', '{{.Image}}', 'fs-hermes-fc'],
                             capture_output=True, text=True, timeout=10)
    if checked.returncode:
        # The original unit uses --rm and Restart=no: a failed worker may have
        # no container. Only pre-install checks can use its exact installed unit
        # and locally present pinned image; post-restart still requires a container.
        if (not allow_stopped or checked.returncode != 1
                or checked.stderr.strip() != 'Error: No such object: fs-hermes-fc'):
            raise ValueError('current_worker_container_unavailable')
        def output(command):
            return subprocess.check_output(command, universal_newlines=True, timeout=10).strip()
        if output(['docker', 'ps', '-a', '--filter', 'name=^/fs-hermes-fc$', '--format', '{{.ID}}']):
            raise ValueError('worker_container_changed_during_observation')
        unit = '/etc/systemd/system/fs-hermes-fc.service'
        dropin = unit + '.d/install-state-isolation.conf'
        expected = {unit: '94b9cf19547ad0a4b68307ea35d4f5317fca0136048b90d78d5f9cea1dbaf011',
                    dropin: '2a4eeada8c0acd27db04aa14838af7cc5c7fe3355677581d53f1f3509c74321a'}
        base = frozen()
        for name, sha in expected.items():
            path = Path(name)
            base.no_target_link(path)
            info = path.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or (info.st_uid, info.st_gid) != (0, 0)
                    or stat.S_IMODE(info.st_mode) & 0o022
                    or hashlib.sha256(path.read_bytes()).hexdigest() != sha):
                raise ValueError('stopped_worker_unit_drift')
        state = dict(line.split('=', 1) for line in output([
            'systemctl', 'show', 'fs-hermes-fc.service', '-p', 'ActiveState',
            '-p', 'FragmentPath', '-p', 'DropInPaths', '-p', 'NeedDaemonReload']).splitlines())
        if (state.get('ActiveState') not in ('failed', 'inactive')
                or state.get('FragmentPath') != unit or state.get('DropInPaths') != dropin
                or state.get('NeedDaemonReload') != 'no'):
            raise ValueError('stopped_worker_unit_state_changed')
        # Both exact unit bytes above pin this image; do not resolve mutable tags
        # or substitute another image when recovery is needed.
        value = output(['docker', 'image', 'inspect', '--format', '{{.Id}}', FROZEN_IMAGE_MARKER])
        if value != FROZEN_IMAGE_MARKER:
            raise ValueError('stopped_worker_pinned_image_unavailable')
    else:
        value = checked.stdout.strip()
        state = dict(line.split('=', 1) for line in subprocess.check_output([
            'systemctl', 'show', 'fs-hermes-fc.service', '-p', 'ActiveState'],
            universal_newlines=True, timeout=10).splitlines())
    if not re.fullmatch('sha256:[a-f0-9]{64}', value):
        raise ValueError('current_worker_image_required')
    if state['ActiveState'] not in ('active', 'failed', 'inactive'):
        raise ValueError('worker_state_not_stable')
    return {'image': value, 'state': state['ActiveState'],
            'source': 'configured_unit_and_local_image' if checked.returncode else 'container'}


def worker_image(*, allow_stopped=False):
    return worker_observation(allow_stopped=allow_stopped)['image']


def quiescent(base, root):
    # The original requests/provider fences remain, with both conversation lanes,
    # tracking and learning added before either install or rollback can restart.
    for name, table, states in (
        ('conversations/conversations.db', 'turns', ('preparing', 'dispatch_unknown', 'queued', 'running', 'stopping')),
        ('pricing-reviews/conversations.db', 'turns', ('preparing', 'dispatch_unknown', 'queued', 'running', 'stopping')),
        ('tasks.sqlite3', 'tasks', ('QUEUED', 'DISPATCH_UNKNOWN', 'RUNNING', 'VALIDATING', 'NEEDS_RECONCILE')),
        ('tasks.sqlite3', 'learning_events', ('running', 'unknown')),
        ('customer-tracking/tracking.db', 'scan_jobs', ('pending',)),
        ('customer-tracking/tracking.db', 'milestones', ('claimed', 'creating', 'dispatch_unknown', 'queued', 'running'))):
        path = base.rooted(root, '/var/lib/fs-hermes-fc/fs/' + name)
        base.no_target_link(path)
        if not path.exists():
            if name == 'conversations/conversations.db' or name == 'tasks.sqlite3':
                raise ValueError('existing_material_task_store_required')
            continue
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                if table != 'learning_events':
                    raise ValueError('unknown_material_store_schema')
                continue
            query = 'SELECT count(*) FROM ' + table + ' WHERE state IN (' + ','.join('?' for _ in states) + ')'
            if db.execute(query, states).fetchone()[0]:
                raise ValueError('active_or_unknown_material_task')


def load_base():
    approved = json.loads((HERE / 'approved-manifest.json').read_text('utf-8'))
    if approved.get('materialDiagnostics') is True:
        configure_diagnostics()
    elif approved.get('materialExecution') is True:
        configure_execution()
    base = frozen()
    git_baseline = None
    if approved.get('installedBaseline'):
        raw = (HERE / 'payload-manifest.json').read_bytes()
        if hashlib.sha256(raw).hexdigest() != approved['approvedPayloadSha256']:
            raise ValueError('installed_git_descriptor_drift')
        git_baseline = json.loads(raw).get('installed_baseline')
    validate = base.validate

    def exact(manifest, stage):
        if DIAGNOSTICS_MODE and (manifest.get('materialDiagnostics') is not True or
                manifest.get('installedBaseline') != INSTALLED_PROOF or
                manifest.get('runtimeBefore') != manifest.get('runtimeRequired') or
                manifest.get('workerImageSource') != 'container' or
                manifest.get('materialChangedTargets') != [r['target'] for r in manifest.get('files', [])
                                                          if r['beforeSha256'] != r['sha256']] or
                any(r['beforeSha256'] != r['sha256'] and r['candidate'] not in
                    ('http/conversation_http.py', 'http/range_api.py') for r in manifest.get('files', []))):
            raise ValueError('exact_material_diagnostics_delta_required')
        if manifest != approved or manifest.get('scope') != SCOPE:
            raise ValueError('exact_material_manifest_required')
        if manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:
            raise ValueError('material_readonly_business_boundary')
        observed = datetime.fromisoformat(manifest['baselineObservedAt'])
        if observed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 3600:
            raise ValueError('fresh_material_baseline_required')
        if not re.fullmatch('sha256:[a-f0-9]{64}', manifest.get('workerImageId', '')):
            raise ValueError('material_worker_image_required')
        installed = manifest.get('installedBaseline')
        if installed is not None and installed != INSTALLED_PROOF:
            raise ValueError('exact_installed_release_required')
        if installed and (not isinstance(git_baseline, dict)
                          or git_baseline.get('source_commit') != INSTALLED_COMMIT
                          or set(git_baseline.get('files', {})) != set(TARGETS)):
            raise ValueError('installed_git_baseline_required')
        for row in manifest.get('files', []):
            wrong_before = (row.get('beforeSha256') != git_baseline['files'][row['candidate']] if installed
                            else (row.get('beforeSha256') is None) != (row['candidate'] in NEW))
            if (wrong_before
                    or row.get('owner') != '0:0'
                    or row.get('mode') != ('0o600' if row['target'] == NGINX else '0o644')):
                raise ValueError('material_existing_new_or_mode_boundary')
        if manifest.get('runtimeRequired') != {unit: {'ActiveState': 'active'} for unit in (
                'fs-business-range.service', 'fs-hermes-fc.service', 'nginx.service')}:
            raise ValueError('material_active_services_required')
        before = manifest.get('runtimeBefore', {})
        if (set(before) != set(manifest['runtimeRequired'])
                or before['fs-business-range.service'] != {'ActiveState': 'active'}
                or before['nginx.service'] != {'ActiveState': 'active'}
                or before['fs-hermes-fc.service'] not in [
                    {'ActiveState': state} for state in ('active', 'inactive', 'failed')]
                or manifest.get('workerImageSource') not in ('container', 'configured_unit_and_local_image')
                or (manifest['workerImageSource'] == 'configured_unit_and_local_image'
                    and before['fs-hermes-fc.service']['ActiveState'] == 'active')):
            raise ValueError('material_runtime_before_required')
        static = manifest.get('materialStaticOnly', False)
        if type(static) is not bool or static and (
                not installed or manifest['runtimeBefore'] != manifest['runtimeRequired']
                or manifest['workerImageSource'] != 'container'
                or any(row['beforeSha256'] != row['sha256'] and not row['candidate'].startswith('frontend/')
                       for row in manifest['files'])):
            raise ValueError('exact_static_material_delta_required')
        if {row['path'] for row in manifest.get('unchangedRequired', [])} != protected_paths(base):
            raise ValueError('material_protected_set_changed')
        return validate(manifest, stage)

    base.validate = exact
    original_group = base.approved_daily_group
    base.approved_daily_group = lambda manifest, root, item, info: original_group(manifest, root, item, info) or (
        manifest.get('scope') == SCOPE and item == base.rooted(root, '/var/lib/fs-hermes-fc')
        and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (0, 9876, 0o750))
    original_idle = base.hermes_quiescent

    def idle(root):
        original_idle(root)
        quiescent(base, root)

    base.hermes_quiescent = idle
    original_guards = base.guards
    before_restart = True

    def guards(manifest, root, reader_stopped=False):
        # runtimeRequired is the successful postcondition, runtimeBefore is the
        # explicit observed precondition. Never fake an active worker to the
        # frozen checks, and retain every other guard/protected source check.
        if manifest.get('installedBaseline'):
            installed_baseline(root, git_baseline)
        if before_restart and manifest.get('scope') == SCOPE:
            if manifest['runtimeBefore']['fs-hermes-fc.service'] != {'ActiveState': 'active'}:
                observed = worker_observation(allow_stopped=True)
                if (observed['image'] != manifest['workerImageId']
                        or observed['source'] != manifest['workerImageSource']):
                    raise ValueError('material_recovery_image_source_drift')
            manifest = dict(manifest, runtimeRequired=manifest['runtimeBefore'])
        return original_guards(manifest, root, reader_stopped=reader_stopped)

    base.guards = guards
    original_atomic, original_apply = base.atomic, base.apply
    publish_root = Path('/')

    def atomic(path, payload, mode=0o644):
        # Keep the original writer/journal and every per-row guard. Static-only
        # follow-ups leave identical active targets (including runtime) untouched.
        if approved.get('materialStaticOnly') or approved.get('materialDiagnostics'):
            for row in approved['files']:
                if path == base.rooted(publish_root, row['target']) and row['beforeSha256'] == row['sha256']:
                    if (hashlib.sha256(payload).hexdigest() != row['sha256']
                            or base.digest(path) != row['sha256'] or mode != int(row['mode'], 8)):
                        raise ValueError('unchanged_static_target_drift')
                    return
        return original_atomic(path, payload, mode)

    def apply(manifest, stage, approved_sha, manifest_bytes, release_id, root=Path('/')):
        nonlocal publish_root
        publish_root = root
        return original_apply(manifest, stage, approved_sha, manifest_bytes, release_id, root)

    base.atomic, base.apply = atomic, apply
    original_inspect = base.inspect

    def inspect(manifest, stage, root=Path('/')):
        result = original_inspect(manifest, stage, root)
        if root == Path('/'):
            for row in manifest['files']:
                path = base.rooted(root, row['target'])
                if path.exists():
                    info = path.stat()
                    if (info.st_uid, info.st_gid, oct(stat.S_IMODE(info.st_mode))) != (0, 0, row['mode']):
                        raise ValueError('material_target_owner_mode_drift')
            if worker_image(allow_stopped=True) != manifest['workerImageId']:
                raise ValueError('material_worker_image_drift')
            # Import definitions only; no service instance, model or source query.
            program = ("import sys;from pathlib import Path;"
                       "sys.path[:0]=sys.argv[1:];"
                       "import conversation_service,conversation_http,conversation_file_tools,conversation_files;"
                       "assert Path(conversation_service.__file__).parent==Path(sys.argv[1]);"
                       "import openpyxl,et_xmlfile")
            if EXECUTION_MODE:
                program += ';import conversation_material_runs,conversation_goals,conversation_goal_tasks,material_execution,b2_goal_host,b2_goal_state'
            checked = subprocess.run(['/opt/python39/bin/python3.9', '-I', '-B', '-c', program,
                                      str((stage / 'candidate/runtime').resolve()),
                                      str((stage / 'candidate/http').resolve()), '/opt/fs-hermes-fc',
                                      '/opt/fs-exact-range-20261001'], capture_output=True, timeout=25)
            if checked.returncode:
                raise ValueError('material_composed_import_failed')
        return result

    base.inspect = inspect
    original_restart = base.restart_for
    helper = HERE / 'release_readiness.py'
    if hashlib.sha256(helper.read_bytes()).hexdigest() != approved.get('readinessSha256'):
        raise ValueError('current_readiness_helper_changed')
    spec = importlib.util.spec_from_file_location('material_readiness', helper)
    readiness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(readiness)

    def restart(manifest, admission_fence=None):
        nonlocal before_restart
        before_restart = False
        if manifest.get('materialStaticOnly'):
            if worker_image() != manifest['workerImageId']:
                raise ValueError('material_worker_image_drift')
            base.guards(manifest, publish_root)
            return  # Static bytes only: no worker/HTTP restart or Nginx reload.
        if manifest.get('materialDiagnostics'):
            # Same original admission fence and DEEP restart on install/rollback;
            # only the existing HTTP process loads changed bytes. Worker/Nginx
            # targets and their running processes are not changed by this mode.
            admission_fence.stop_then_unlock_database()
            result = readiness.restart_with_hermes_readiness(base, original_restart,
                dict(manifest, scope=base.DEEP_SCOPE), admission_fence)
            if worker_image() != manifest['workerImageId']:
                raise ValueError('material_worker_image_drift')
            base.guards(manifest, publish_root)
            return result
        if manifest.get('scope') == SCOPE:
            subprocess.run(['nginx', '-t'], check=True, capture_output=True)
        result = readiness.restart_with_hermes_readiness(base, original_restart, manifest, admission_fence)
        if manifest.get('scope') == SCOPE:
            if worker_image() != manifest['workerImageId']:
                raise ValueError('material_worker_image_drift')
            base.guards(manifest, Path('/'))
            subprocess.run(['systemctl', 'reload', 'nginx.service'], check=True)
        return result

    base.restart_for = restart
    return base


if __name__ == '__main__':
    load_base().main()
