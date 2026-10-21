import importlib.util
import io
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('channel_release_test', ROOT/'deploy/release.py')
release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release)


class Publisher(unittest.TestCase):
    def test_new_cache_schedule_admits_only_its_exact_four_units(self):
        sys.path.insert(0,str(ROOT/'deploy'))
        try:
            spec=importlib.util.spec_from_file_location('channel_cache_release_test',ROOT/'deploy/cache_release.py')
            fix=importlib.util.module_from_spec(spec);spec.loader.exec_module(fix)
            new=frozenset(k for k in fix.TARGETS if k.startswith(('ui/','units/')) or k=='runtime/channel_cache.py')
            with patch.multiple(release,SCOPE=fix.SCOPE,TARGETS=fix.TARGETS,NEW=new,AUTHORIZED_TIMERS=fix.UNITS):
                manifest=dict(scope=fix.SCOPE,businessWrites=False,timersChanged=True,files=[dict(candidate=k,target=v,beforeSha256=None if k in new else 'a'*64,owner='0:0',mode='0o644') for k,v in fix.TARGETS.items()])
                self.assertEqual(len(release.checked_manifest(manifest)['files']),11)
                bad=deepcopy(manifest);bad['files'][-1]['target']='/etc/systemd/system/other.timer'
                with self.assertRaises(ValueError):release.checked_manifest(bad)
                bad=deepcopy(manifest);bad['timersChanged']=False
                with self.assertRaises(ValueError):release.checked_manifest(bad)
        finally:sys.path.pop(0)

    def test_display_only_publication_reloads_nginx_without_stopping_readers(self):
        sys.path.insert(0,str(ROOT/'deploy'))
        try:
            spec=importlib.util.spec_from_file_location('channel_label_test',ROOT/'deploy/label_fix.py')
            fix=importlib.util.module_from_spec(spec);spec.loader.exec_module(fix)
            self.assertEqual(len(fix.TARGETS),4)
            self.assertTrue(all(k.startswith(('ui/','generated/')) for k in fix.TARGETS))
            calls=[];base=SimpleNamespace(restart_for=lambda *a:None)
            with patch.object(fix.release,'load_base',return_value=base),patch('subprocess.run',side_effect=lambda args,**kw:calls.append(args)):
                fix.load_base().restart_for({'scope':fix.SCOPE},SimpleNamespace())
            self.assertEqual(calls,[['nginx','-t'],['systemctl','reload','nginx']])
        finally:sys.path.pop(0)

    def test_directory_entry_rewrites_to_an_exact_file_route(self):
        sys.path.insert(0, str(ROOT/'deploy'))
        try:
            fix_spec = importlib.util.spec_from_file_location('channel_route_test', ROOT/'deploy/route_fix.py')
            fix = importlib.util.module_from_spec(fix_spec); fix_spec.loader.exec_module(fix)
            broken = b'before\nlocation = /dashboard/channel-effects/ {\n    if ($request_method !~ ^(GET|HEAD)$) { return 405; }\n    alias /some/index.html;\n}\nafter'
            corrected = fix.candidate(broken)
            self.assertIn(b'location = /dashboard/channel-effects/index.html {',corrected)
            self.assertIn(b'rewrite ^ /dashboard/channel-effects/index.html last;',corrected)
            self.assertTrue(corrected.startswith(b'before\n') and corrected.endswith(b'\nafter'))
            corrected_crlf = fix.candidate(broken.replace(b'\n',b'\r\n'))
            self.assertEqual(corrected_crlf,corrected.replace(b'\n',b'\r\n'))
            with self.assertRaises(ValueError):fix.candidate(corrected)
        finally:sys.path.pop(0)

    def test_exact_targets_and_existing_file_boundary(self):
        manifest = json.loads((ROOT/'deploy/approved-manifest.json').read_text())
        self.assertEqual(len(release.checked_manifest(manifest)['files']),12)
        bad = deepcopy(manifest); bad['files'][0]['target'] = '/opt/other'
        with self.assertRaises(ValueError): release.checked_manifest(bad)
        bad = deepcopy(manifest); bad['businessWrites'] = True
        with self.assertRaises(ValueError): release.checked_manifest(bad)

    def test_only_range_and_nginx_reload_no_worker_or_automation_change(self):
        base = release.load_base(); calls = []
        fence = SimpleNamespace(stop_then_unlock_database=lambda:calls.append(['fence-stop-range']))
        with patch('subprocess.run',side_effect=lambda args,**kw:calls.append(args)), patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"ok":true}')):
            base.restart_for({'scope':release.SCOPE},fence)
        self.assertIn(['systemctl','restart','fs-business-range.service'], calls)
        self.assertIn(['nginx','-t'],calls)
        self.assertIn(['systemctl','reload','nginx'],calls)
        self.assertFalse(any('fs-hermes-fc.service' in call or any('timer' in item for item in call) for call in calls))


if __name__ == '__main__': unittest.main()
