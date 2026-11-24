"""Offline verification for the customer-maintenance delta builder."""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
sys.path.insert(0, str(ROOT / 'deploy'))
import maintenance_release as release


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