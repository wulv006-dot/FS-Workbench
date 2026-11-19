"""Release boundary checks do not touch production or relax the frozen publisher."""
from pathlib import Path
from hashlib import sha256
import importlib.util
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch as mock_patch, Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy'))
from release import checked_manifest, TARGETS, NEW, SCOPE
from patch_navigation import patch


class Deployment(unittest.TestCase):
    def test_midnight_release_pins_both_shipped_timer_units_and_only_restarts_timers(self):
        repo = ROOT.parents[2]
        adapter = repo/'docs/planning/fs-query-perf-20261119/release_archive_timers.py'
        spec = importlib.util.spec_from_file_location('release_archive_timers',adapter)
        module = importlib.util.module_from_spec(spec)
        with mock_patch.dict(sys.modules, {'release_navigation_base': Mock()}):
            spec.loader.exec_module(module)
        files = [ROOT/'deploy/fs-user-analytics.timer',
                 ROOT.parent/'nightly-pipeline-20261023/deploy/fs-channel-cache.timer']
        self.assertEqual(set(module.UNITS), {file.name for file in files})
        for file in files:
            self.assertEqual(sha256(file.read_bytes().replace(b'\r\n', b'\n')).hexdigest(), module.UNITS[file.name][1])
        with mock_patch.object(module.subprocess, 'run') as run:
            module.reload_timers()
        self.assertEqual(run.call_args_list[1].args[0], ['systemctl', 'restart', *module.UNITS])

    def test_weekly_release_binds_exact_ten_targets_to_existing_host_publisher(self):
        spec=importlib.util.spec_from_file_location('users_weekly_release_test',ROOT/'deploy/release_weekly.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        host=SimpleNamespace(SCOPE='old',TARGETS={},NEW=frozenset(),bind=object())
        original_bind=host.bind
        base=object()
        def original_loader():
            self.assertEqual(host.SCOPE,module.SCOPE)
            self.assertEqual(host.NEW,frozenset({'source/user_weekly.py'}))
            self.assertEqual(set(host.TARGETS.values()),{
                *('/opt/fs-hermes-fc/'+name for name in ('user_runtime.py','user_contract.py','user_jobs.py','user_query.py','user_http.py','user_customer_types.py','user_tools.py','user_weekly.py')),
                '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/index.html',
                '/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.js'})
            self.assertEqual(len(host.TARGETS),10)
            self.assertIs(host.bind,original_bind)
            return base
        p4=SimpleNamespace(load_base=Mock(side_effect=original_loader))
        with mock_patch.dict(sys.modules,{'host_release':host,'p4_release':p4}):
            self.assertIs(module.load_base(),base)
        p4.load_base.assert_called_once_with()
        host.TARGETS.clear()
        self.assertEqual(len(module.TARGETS),10)

    def test_weekly_release_does_not_hide_original_publisher_rejection(self):
        spec=importlib.util.spec_from_file_location('users_weekly_release_rejection_test',ROOT/'deploy/release_weekly.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        host=SimpleNamespace(SCOPE='old',TARGETS={},NEW=frozenset())
        p4=SimpleNamespace(load_base=Mock(side_effect=ValueError('exact_host_tiered_scope_required')))
        with mock_patch.dict(sys.modules,{'host_release':host,'p4_release':p4}):
            with self.assertRaisesRegex(ValueError,'exact_host_tiered_scope_required'):
                module.load_base()

    def test_january_extension_cannot_change_other_runtime_or_schedule(self):
        import release
        with mock_patch.dict(sys.modules),mock_patch.multiple(release,SCOPE=release.SCOPE,TARGETS=release.TARGETS,NEW=release.NEW,AUTHORIZED_TIMERS=release.AUTHORIZED_TIMERS):
            spec=importlib.util.spec_from_file_location('users_january_release_test',ROOT/'deploy/release_january.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertEqual(set(release.TARGETS),{'runtime/user_config.json','runtime/user_query.py','runtime/backfill_history.py','ui/index.html','ui/users.js'})
            self.assertFalse(release.NEW or release.AUTHORIZED_TIMERS)
            value=dict(scope=release.SCOPE,businessWrites=False,timersChanged=False,files=[dict(candidate=k,target=v,beforeSha256='a'*64,owner='0:0',mode='0o644') for k,v in release.TARGETS.items()])
            self.assertEqual(release.checked_manifest(value),value)
            value['files'][0]['target']='/opt/fs-order-session/service.py'
            with self.assertRaises(ValueError):release.checked_manifest(value)

    def test_search_release_only_restarts_reader_and_reloads_routes(self):
        import release
        with mock_patch.multiple(release,SCOPE=release.SCOPE,TARGETS=release.TARGETS,NEW=release.NEW,AUTHORIZED_TIMERS=release.AUTHORIZED_TIMERS):
            spec=importlib.util.spec_from_file_location('users_search_release_test',ROOT/'deploy/release_search.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertEqual(len(release.TARGETS),8)
            self.assertFalse(release.NEW or release.AUTHORIZED_TIMERS)
            previous=Mock();inspect=Mock();base=SimpleNamespace(restart_for=previous,DEEP_SCOPE='reader',inspect=inspect)
            with mock_patch.object(module.tools,'load_base',return_value=base):base=module.load_base()
            with mock_patch.object(module.subprocess,'check_output',return_value='sha256:current\n'):
                base.inspect({'imageId':'sha256:current'},'stage')
                inspect.assert_called_once_with({'imageId':'sha256:current'},'stage')
                with self.assertRaisesRegex(ValueError,'image_changed'):base.inspect({'imageId':'sha256:old'},'stage')
            with mock_patch.object(module.subprocess,'run') as run:
                with self.assertRaises(ValueError):base.restart_for({'scope':release.SCOPE})
                fence=Mock();base.restart_for({'scope':release.SCOPE},fence)
                fence.stop_then_unlock_database.assert_called_once()
                previous.assert_called_once_with({'scope':'reader'},fence)
                self.assertEqual([c.args[0] for c in run.call_args_list],[['nginx','-t'],['systemctl','reload','nginx']])

    def test_period_release_keeps_original_cas_and_cannot_touch_prices(self):
        import release
        with mock_patch.multiple(release,SCOPE=release.SCOPE,TARGETS=release.TARGETS,NEW=release.NEW,AUTHORIZED_TIMERS=release.AUTHORIZED_TIMERS):
            spec=importlib.util.spec_from_file_location('users_period_release_test',ROOT/'deploy/release_period.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            value=dict(scope=release.SCOPE,businessWrites=False,timersChanged=False,files=[dict(candidate=k,target=v,beforeSha256=None if k in release.NEW else 'a'*64,owner='0:0',mode='0o644') for k,v in release.TARGETS.items()])
            self.assertEqual(len(value['files']),10)
            self.assertEqual(release.NEW,frozenset(['runtime/user_customer_types.py']))
            self.assertEqual(release.checked_manifest(value),value)
            value['files'][0]['target']='/opt/fc27-cloud-browser/price_writer.py'
            with self.assertRaises(ValueError):release.checked_manifest(value)

    def test_manifest_rejects_extra_target_and_existing_source_without_cas(self):
        def manifest():
            return dict(scope=SCOPE,businessWrites=False,timersChanged=True,files=[dict(candidate=k,target=v,beforeSha256=None if k in NEW else 'a'*64,owner='0:0',mode='0o644') for k,v in TARGETS.items()])
        value=manifest();self.assertEqual(checked_manifest(value),value)
        value['files'][0]['target']='/opt/fc27-cloud-browser/price_writer.py'
        with self.assertRaises(ValueError):checked_manifest(value)
        value=manifest();next(r for r in value['files'] if r['candidate'] not in NEW)['beforeSha256']=None
        with self.assertRaises(ValueError):checked_manifest(value)
        value=manifest();value['timersChanged']=False
        with self.assertRaises(ValueError):checked_manifest(value)

    def test_navigation_requires_exact_active_bytes(self):
        with self.assertRaisesRegex(ValueError,'navigation_baseline_drift'):
            patch({'navigation.json':b'{}','hubnav.js':b'','navigation.conf':b''})

    def test_job_reload_keeps_other_services_and_schedule(self):
        import release
        with mock_patch.multiple(release,SCOPE=release.SCOPE,TARGETS=release.TARGETS,NEW=release.NEW,AUTHORIZED_TIMERS=release.AUTHORIZED_TIMERS):
            spec=importlib.util.spec_from_file_location('users_job_release_test',ROOT/'deploy/release_jobs.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertEqual(len(release.TARGETS),7)
            self.assertEqual({k for k in release.TARGETS if k.startswith('units/')},{'units/fs-user-analytics.service'})
            previous=Mock();base=SimpleNamespace(restart_for=previous)
            with mock_patch.object(module.tools,'load_base',return_value=base):base=module.load_base()
            with mock_patch.object(module.subprocess,'run') as run:
                with self.assertRaisesRegex(ValueError,'admission_fence'):base.restart_for({'scope':release.SCOPE})
                run.assert_not_called()
                base.restart_for({'scope':release.SCOPE},object())
                previous.assert_called_once()
                self.assertEqual([c.args[0] for c in run.call_args_list],[['systemctl','daemon-reload'],['systemctl','is-active','--quiet','fs-user-analytics.timer']])
