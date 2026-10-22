"""Release boundary checks do not touch production or relax the frozen publisher."""
from pathlib import Path
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
