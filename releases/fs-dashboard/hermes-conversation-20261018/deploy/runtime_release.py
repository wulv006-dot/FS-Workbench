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
    'runs_contract.py', 'proxy_gateway.py')}
TARGETS.update({'http/conversation_http.py': '/opt/fs-exact-range-20261001/conversation_http.py',
                'http/formal.conf': NGINX})
TARGETS.update({'frontend/' + name: '/var/www/dashboard/fs-home/hermes/conversation/' + name
                for name in ('index.html', 'conversation.js', 'conversation.css')})
NEW = frozenset('runtime/' + name for name in (
    'conversation_files.py', 'conversation_file_bindings.py',
    'conversation_file_tools.py', 'material_evidence.py'))


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


def worker_image():
    value = subprocess.check_output(['docker', 'inspect', '--format', '{{.Image}}', 'fs-hermes-fc'],
                                    universal_newlines=True).strip()
    if not re.fullmatch('sha256:[a-f0-9]{64}', value):
        raise ValueError('current_worker_image_required')
    return value


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
    base = frozen()
    approved = json.loads((HERE / 'approved-manifest.json').read_text('utf-8'))
    validate = base.validate

    def exact(manifest, stage):
        if manifest != approved or manifest.get('scope') != SCOPE:
            raise ValueError('exact_material_manifest_required')
        if manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False:
            raise ValueError('material_readonly_business_boundary')
        observed = datetime.fromisoformat(manifest['baselineObservedAt'])
        if observed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 3600:
            raise ValueError('fresh_material_baseline_required')
        if not re.fullmatch('sha256:[a-f0-9]{64}', manifest.get('workerImageId', '')):
            raise ValueError('material_worker_image_required')
        for row in manifest.get('files', []):
            if ((row.get('beforeSha256') is None) != (row['candidate'] in NEW)
                    or row.get('owner') != '0:0'
                    or row.get('mode') != ('0o600' if row['target'] == NGINX else '0o644')):
                raise ValueError('material_existing_new_or_mode_boundary')
        if manifest.get('runtimeRequired') != {unit: {'ActiveState': 'active'} for unit in (
                'fs-business-range.service', 'fs-hermes-fc.service', 'nginx.service')}:
            raise ValueError('material_active_services_required')
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
            if worker_image() != manifest['workerImageId']:
                raise ValueError('material_worker_image_drift')
            # Import definitions only; no service instance, model or source query.
            program = ("import sys;from pathlib import Path;"
                       "sys.path[:0]=sys.argv[1:];"
                       "import conversation_service,conversation_http,conversation_file_tools,conversation_files;"
                       "assert Path(conversation_service.__file__).parent==Path(sys.argv[1]);"
                       "import openpyxl,et_xmlfile")
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
        if manifest.get('scope') == SCOPE:
            subprocess.run(['nginx', '-t'], check=True, capture_output=True)
        result = readiness.restart_with_hermes_readiness(base, original_restart, manifest, admission_fence)
        if manifest.get('scope') == SCOPE:
            if worker_image() != manifest['workerImageId']:
                raise ValueError('material_worker_image_drift')
            subprocess.run(['systemctl', 'reload', 'nginx.service'], check=True)
        return result

    base.restart_for = restart
    return base


if __name__ == '__main__':
    load_base().main()
