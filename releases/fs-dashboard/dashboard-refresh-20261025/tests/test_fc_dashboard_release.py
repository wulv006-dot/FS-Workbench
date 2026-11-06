import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'deploy/fc_dashboard_release.py'
spec = importlib.util.spec_from_file_location('fc_dashboard_release', PATH)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTargetTest(unittest.TestCase):
    def test_exact_complete_payload_uses_existing_publisher(self):
        original = object()
        adapter = types.SimpleNamespace(load_base=lambda: original)
        with patch.dict(sys.modules, {'actual_release': adapter}):
            self.assertIs(release.load_base('fc-dashboard-20261106-0123456789ab'), original)
        self.assertEqual(len(adapter.TARGETS), 12)
        self.assertEqual(adapter.SCOPE, release.SCOPE)
        self.assertEqual(adapter.TARGETS['source/fc_dashboard.py'], '/opt/fs-exact-range-20261001/fc_dashboard.py')
        self.assertEqual(adapter.NEW, frozenset('source/' + name for name in
            ('business.js', 'home-business.js', 'legacy-business.js', 'business.css',
             'shell.js', 'home-shell.js', 'legacy-shell.js', 'fc_dashboard.py')))
        for name in ('shell.js', 'home-shell.js', 'legacy-shell.js'):
            self.assertEqual(adapter.TARGETS['source/' + name],
                '/var/lib/fs-navigation-formal-static/fc-dashboard-20261106-0123456789ab/' + name)
        self.assertNotIn('source/range_api.py', adapter.TARGETS)
        self.assertFalse(any('timer' in path or 'credential' in path for path in adapter.TARGETS.values()))

    def test_historical_or_unversioned_target_cannot_be_replayed(self):
        for value in ('fc-dashboard', 'fc-dashboard-20261106-current', '../unexpected'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                release.load_base(value)


if __name__ == '__main__':
    unittest.main()
