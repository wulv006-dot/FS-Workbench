import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE = Path(__file__).resolve().parents[1] / 'modules/navigation-experience/prepare-navigation.py'
MAIN = '/etc/nginx/conf.d/iggm-web.conf'
FORMAL = '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
USERS = '/var/lib/fs-navigation-formal-static/users/index.html'
CUSTOMERS = '/var/lib/fs-navigation-formal-static/customers/index.html'
SHELL = '/var/lib/fs-navigation-formal-static/workspace/shell.js'
HOME = '/var/www/dashboard/fs-home/index.html'
BUSINESS_HTML = '/var/www/dashboard/index.html'
HUB = '/var/www/hub/hubnav.js'
NAV = '/var/www/hub/nav.js'


class NavigationReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.before = {
            MAIN: b"""server {
    sub_filter '</body>' '<script src="/__hub/hubnav.js?v=main-old"></script></body>';
    location /__hub/ {
        alias /var/www/hub/;
        add_header Cache-Control "public, max-age=2592000";
    }
}
""",
            FORMAL: f"""location = /dashboard/users/index.html {{
    alias {USERS};
    sub_filter '</head>' '<link rel="preload" as="script" href="/__hub/hubnav.js?v=old">';
}}
location = /dashboard/customers/index.html {{
    alias {CUSTOMERS};
    sub_filter '</body>' '<script defer src="/__hub/hubnav.js?v=customer"></script>';
}}
location = /dashboard/workspace-assets/workspace/shell.js {{
    alias {SHELL};
    expires -1;
}}
""".encode(),
            USERS: b'<script src="/__hub/hubnav.js"></script>',
            CUSTOMERS: b'<script src="/__hub/nav.js?v=customer"></script>',
            SHELL: b"new URL('/__hub/hubnav.js?v=shell', document.baseURI);",
            BUSINESS_HTML: b'<!-- the server injects /__hub/hubnav.js -->',
            HOME: b'<script src="/__hub/nav.js?v=home"></script>',
            HUB: '/* 数据分析 → 客户维护 */'.encode(),
            NAV: '/* 数据分析 → 客户维护，静态导航 */'.encode(),
        }
        for target, raw in self.before.items():
            path = self.root / target[1:]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        spec = importlib.util.spec_from_file_location('prepare_navigation', MODULE)
        self.release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.release)

    def test_stale_and_unversioned_references_roll_together(self):
        output = self.root / 'stage'
        result = self.release.prepare(self.root, output)
        version = result['version']
        manifest = result['manifest']
        candidates = {}
        for row in manifest['files']:
            raw = (output / 'candidate' / row['candidate']).read_bytes()
            self.assertEqual(row['beforeSha256'], self.release.sha(self.before[row['target']]))
            self.assertEqual(row['sha256'], self.release.sha(raw))
            candidates[row['target']] = raw
        self.assertEqual(set(candidates), {MAIN, FORMAL, USERS, CUSTOMERS, SHELL, HOME})
        self.assertEqual(
            {row['path'] for row in manifest['unchangedRequired']}, {HUB, NAV, BUSINESS_HTML},
        )
        for target, raw in candidates.items():
            refs = self.release.references(raw, nginx=target in (MAIN, FORMAL))
            self.assertTrue(refs)
            self.assertTrue(all(ref.endswith(b'?v=' + version.encode()) for ref in refs))
        self.assertIn(b'public, max-age=2592000', candidates[MAIN])
        self.assertEqual(candidates[MAIN].count(b'public, max-age=300, stale-while-revalidate=604800'), 2)
        self.assertIn(b'location = /__hub/hubnav.js {', candidates[MAIN])
        self.assertIn(b'location = /__hub/nav.js {', candidates[MAIN])
        self.assertEqual(self.release.apply_cache_policy(candidates[MAIN]), candidates[MAIN])

        for target, raw in candidates.items():
            (self.root / target[1:]).write_bytes(raw)
        self.assertEqual(self.release.prepare(self.root, self.root / 'no-op')['manifest']['files'], [])

    def test_either_script_change_rolls_every_consumer(self):
        before = self.release.prepare(self.root, self.root / 'before')['version']
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for target in (HUB, NAV):
            name = Path(target).name
            (scripts / name).write_bytes(self.before[target])
        for changed in (HUB, NAV):
            path = scripts / Path(changed).name
            path.write_bytes(self.before[changed] + b'\n// new navigation')
            result = self.release.prepare(self.root, self.root / ('changed-' + path.stem), scripts)
            self.assertNotEqual(result['version'], before)
            self.assertEqual(
                {row['target'] for row in result['manifest']['files']},
                {MAIN, FORMAL, USERS, CUSTOMERS, SHELL, HOME, changed},
            )
            path.write_bytes(self.before[changed])

    def test_cache_drift_stops_and_non_navigation_assets_stay_unchanged(self):
        main = self.before[MAIN]
        self.assertRaises(ValueError, self.release.apply_cache_policy, main.replace(b'2592000', b'60'))
        self.assertRaises(
            ValueError, self.release.apply_cache_policy,
            main + b'    location = /__hub/nav.js { return 404; }\n',
        )
        raw = b'<script src="/__hub/navigation-experience.js?v=keep"></script>\n'
        self.assertEqual(self.release.replace_references(raw, 'nav-test'), raw)
        comment = b'<!-- <script src="/__hub/hubnav.js"></script> -->'
        self.assertEqual(
            self.release.replace_references(comment + self.before[USERS], 'nav-test', html=True),
            comment + b'<script src="/__hub/hubnav.js?v=nav-test"></script>',
        )


if __name__ == '__main__':
    unittest.main()
