"""Offline verification for the customer-maintenance delta builder."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
sys.path.insert(0, str(ROOT / 'deploy'))
import maintenance_release as release


def exercise_rollback_runtime(root):
    from tracking_controller import TrackingController
    from maintenance_ledger import Ledger
    import maintenance_reconcile

    now = datetime.now(timezone.utc)
    root.mkdir(mode=0o700)
    user = 'admin'
    initial = TrackingController(root, lambda user: user == 'admin', auto_start=False)
    ledger = Ledger(initial.store.db)
    ledger.save_rule('rule', 0, dict(enabled=True, priority=0, daily_quota=4, template={'id': 123}), user, now)
    ledger.set_auto('rule', True, user, now)
    expected = {}
    for name in ('job', 'unknown', 'register', 'unsent'):
        ident = ledger.enqueue(name, name, name + '@example.net', 'rule', now)
        ledger.commit_review(ident, dict(decision='pass', digest=name), name, now)
        ledger.decide(ident, 'confirmed', user, now)
        if name != 'unsent':
            row = ledger.claim(ident, now)
            receipt = {'job': {'state':'pending', 'job_id':'original-job'},
                       'unknown': {'state':'unknown'},
                       'register': {'state':'pending_register'}}[name]
            ledger.result(ident, 'dispatching', receipt, now)
            expected[name] = (ident, row['batch'])
        else:
            expected[name] = (ident, None)
    with patch.dict(os.environ, {'FS_CUSTOMER_MAINTENANCE_DISPATCH':'1'}), patch('threading.Thread') as thread:
        controller = TrackingController(root, lambda user: user == 'admin')
    phase_loops = {call.kwargs['args'][0] for call in thread.call_args_list if 'args' in call.kwargs}
    assert phase_loops == {'reconcile'}, phase_loops
    assert ledger.entry(expected['unsent'][0])['state'] == 'void'
    rule, = ledger.rules()
    assert not rule['enabled'] and not rule['auto_enabled']

    def lookup(job, email, batch):
        assert (job, email, batch) == ('original-job', 'job@example.net', expected['job'][1])
        return {'state':'confirmed', 'member_coupon_id':'222'}

    with patch.object(maintenance_reconcile, 'read_job', lookup):
        controller.reconcile_maintenance()
    assert ledger.entry(expected['job'][0])['state'] == 'issued'

    query = dict(mode=['hermes'], structure=['customer_tracking'], view=['phase_manual'])
    code, result = controller.get(user, query)
    assert code == 200 and {row['id'] for row in result['items']} == {expected[k][0] for k in ('unknown', 'register')}
    for kind in ('unknown', 'register'):
        ident, batch = expected[kind]
        payload = dict(kind='hermes_customer_tracking', action='phase_result', id=ident,
                       batch=batch, state='manually_closed', evidence='checked original batch')
        for action in (lambda: controller.post('viewer', payload), lambda: controller.get('viewer', query)):
            try:
                action()
            except PermissionError:
                pass
            else:
                raise AssertionError('non-admin admitted')
        assert controller.post(user, payload) == (200, {'changed': True})
        assert ledger.entry(ident)['state'] == 'manually_closed'
    try:
        controller.post(user, dict(kind='hermes_customer_tracking', action='phase_rule'))
    except ValueError:
        pass
    else:
        raise AssertionError('phase rule write enabled during rollback')
    assert 'maintenance_dispatch' not in sys.modules
    assert 'maintenance_service' not in sys.modules


class MaintenanceRelease(unittest.TestCase):
    def test_old_path_redirects_and_every_new_static_route_retains_actual_guard(self):
        fixture = 'unrelated\n'
        for route, file in (('', 'index.html'), ('page.js', 'tracking-page.js'), ('page.css', 'page.css')):
            fixture += ('location = ' + release.OLD + route + ' {\n'
                        + '    ' + release.GUARD + '\n    alias /var/www/example/' + file + ';\n}\n')
        result = release.replace_routes(fixture)
        self.assertIn('location = ' + release.OLD + ' { return 302 ' + release.NEW + '; }', result)
        self.assertIn(release.NEW + 'reconcile/', result)
        self.assertIn(release.STATIC + '/phase.js', result)
        self.assertEqual(7, result.count(release.GUARD))
        self.assertIn('unrelated', result)
        with self.assertRaises(ValueError):
            release.replace_routes(fixture.replace(release.GUARD, ''))

    def test_live_tracking_rewrite_uses_guarded_html_location(self):
        entry = (f'location = {release.OLD} {{\n    {release.GUARD}\n'
                 f'    rewrite ^ {release.OLD}index.html last;\n}}\n')
        current = entry
        for name in ('index.html', 'page.js', 'page.css'):
            current += (f'location = {release.OLD}{name} {{\n    {release.GUARD}\n'
                        f'    alias /active/{name};\n}}\n')
        forward = release.replace_routes(current)
        self.assertNotIn('rewrite ^', forward)
        self.assertIn(f'location = {release.OLD}index.html {{ return 302 {release.NEW}; }}', forward)
        self.assertIn(f'alias {release.STATIC}/index.html;', forward)
        recovery = release.replace_routes(current, reconcile_only=True)
        self.assertTrue(recovery.startswith(current.rstrip() + '\n\n'))
        self.assertIn(f'alias {release.STATIC}/reconcile.html;', recovery)
        with self.assertRaises(ValueError):
            release.replace_routes(current.replace(release.GUARD + '\n    alias /active/index.html;',
                                                   'alias /active/index.html;'))

    @unittest.skipUnless(os.name == 'posix', 'checks POSIX directory and file modes')
    def test_static_writer_overrides_private_umask_for_exact_nginx_assets(self):
        def atomic(path, data, mode=0o644):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(mode)

        def no_target_link(path):
            if path.exists() and not path.is_file():
                raise ValueError('target is not a regular file')

        publisher = SimpleNamespace(atomic=atomic, no_target_link=no_target_link)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / release.STATIC.lstrip('/') / 'index.html'
            target.parent.parent.mkdir(parents=True)
            release.bind_static_permissions(publisher, root)
            before = os.umask(0o077)
            try:
                publisher.atomic(target, b'page')
                unrelated = root / 'backup' / 'journal.json'
                publisher.atomic(unrelated, b'{}', 0o600)
            finally:
                os.umask(before)
            self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)
            self.assertEqual(stat.S_IMODE(unrelated.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(unrelated.stat().st_mode), 0o600)

    def test_rollback_candidate_keeps_only_the_manual_and_reconcile_surfaces(self):
        routes = ''
        for name in ('', 'page.js', 'page.css'):
            routes += (f'location = {release.OLD}{name} {{\n'
                       f'    {release.GUARD}\n    alias /old/{name or "index.html"};\n}}\n')
        current = json.loads((REPO / release.CONNECTOR).read_bytes())
        prior_catalog = dict(current, operations=[
            dict(row, permission_path=release.OLD) if row['name'].startswith('customer_tracking.') else row
            for row in current['operations'] if not row['name'].startswith('customer_tracking.stage_')
        ])
        for guide in prior_catalog['data_methods']['guides']:
            guide['operations'] = [name for name in guide['operations'] if not name.startswith('customer_tracking.stage_')]
        registry = json.dumps(dict(sections=[
            dict(id='analytics', ids=['user-analytics']), dict(id='brain', ids=['customer-tracking'], intro=''),
        ], tools=[dict(id='customer-tracking', section='brain', path=release.OLD)]))
        active = dict(routes=routes, registry=registry, hubnav='const BUILTIN=' + registry + ';',
                      nav='const registry=' + registry + ';',
                      iam='("/dashboard/fs-home/brain", "/dashboard/fs-home/hermes",',
                      catalog=json.dumps(prior_catalog))
        with TemporaryDirectory() as root:
            root = Path(root)
            baseline, output, composed = (root / name for name in ('baseline', 'out', 'composed'))
            baseline.mkdir()
            composed.mkdir()
            prior = dict.fromkeys(release.TARGETS.values())
            for name, value in active.items():
                raw = value.encode()
                (baseline / name).write_bytes(raw)
                prior[release.ACTIVE[name]] = release.sha(raw)
            (baseline / 'sha256.json').write_text(json.dumps(prior), encoding='utf-8')

            def read_blob(args):
                return (REPO / args[-1].split(':', 1)[1]).read_bytes()

            with patch.object(release.subprocess, 'check_output', side_effect=read_blob):
                forward = release.prepare(REPO, baseline, output, '1'*40)
            rollback = json.loads((output / 'rollback-manifest.json').read_bytes())
            forward_shas = {row['target']: row['sha256'] for row in forward['files']}
            rollback_rows = {row['target']: row for row in rollback['files']}
            for row in rollback['files']:
                self.assertEqual(forward_shas[row['target']], row['beforeSha256'])
                self.assertEqual(row['sha256'], release.sha((output / row['candidate']).read_bytes()))
            rolled_routes = (output / rollback_rows[release.NGINX]['candidate']).read_text('utf-8')
            self.assertIn(routes, rolled_routes)
            self.assertNotIn('return 302', rolled_routes)
            for suffix in ('reconcile/', 'phase.js', 'page.css'):
                self.assertIn('location = ' + release.NEW + suffix, rolled_routes)
            self.assertEqual(6, rolled_routes.count(release.GUARD))
            self.assertIn(release.ACTIVE['iam'], rollback_rows)
            restored_registry = (output / rollback_rows[release.ACTIVE['registry']]['candidate']).read_text('utf-8')
            self.assertEqual(registry, restored_registry)
            page = (output / rollback_rows[release.STATIC + '/reconcile.html']['candidate']).read_text('utf-8')
            self.assertIn('href="' + release.OLD + '"', page)

            for manifest in (forward, rollback):
                for row in manifest['files']:
                    if row['target'].startswith('/opt/fs-hermes-fc/'):
                        (composed / Path(row['target']).name).write_bytes((output / row['candidate']).read_bytes())
            with patch.object(sys, 'path', [str(composed), str(ROOT / 'source'), *sys.path]), patch.dict(sys.modules):
                for name in ('tracking_controller', 'vip_maintenance', 'maintenance_ledger', 'maintenance_review',
                             'maintenance_reconcile', 'maintenance_service', 'maintenance_dispatch'):
                    sys.modules.pop(name, None)
                exercise_rollback_runtime(root / 'db')

    def test_the_shared_module_is_not_a_publication_payload(self):
        self.assertFalse(any('customer_segments.py' in target for target in release.TARGETS.values()))

    def test_current_repository_navigation_and_catalog_stay_in_scope(self):
        registry = json.loads((REPO / 'ui-system/modules/native/navigation.json').read_bytes())
        groups = {row['id']: row['ids'] for row in registry['sections']}
        self.assertNotIn('customer-tracking', groups['brain'])
        adjacent = groups['analytics'].index('user-analytics')
        self.assertEqual('customer-tracking', groups['analytics'][adjacent+1])
        for name in ('hubnav.live.js', 'nav.live.js'):
            script = (REPO / release.NAV / name).read_text('utf-8')
            self.assertIn(release.NEW, script)
            self.assertNotIn(release.OLD, script)
        doc = json.loads((REPO / release.CONNECTOR).read_bytes())
        operations = [r for r in doc['operations'] if r['name'].startswith('customer_tracking.')]
        self.assertTrue(all(r['method']=='GET' and r['permission_path']==release.NEW for r in operations))
        new = next(r for r in operations if r['name']=='customer_tracking.stage_groups')
        self.assertEqual('phase_groups', new['fixed']['view'])