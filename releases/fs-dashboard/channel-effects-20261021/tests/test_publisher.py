import importlib.util
import io
import json
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('channel_release_test', ROOT/'deploy/release.py')
release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release)


class Publisher(unittest.TestCase):
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
