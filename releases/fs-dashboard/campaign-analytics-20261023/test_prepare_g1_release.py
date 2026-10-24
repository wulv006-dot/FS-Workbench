"""Offline packaging behavior; fixture publisher models the exported target/validate API."""
import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path

import prepare_g1_release as package


FIXTURE_PUBLISHER = '''
import hashlib
from pathlib import PurePosixPath
BASE_SHA={base_sha!r}
SCOPE='fs-campaign-dashboard-20261023'
SPECIAL={{'navigation.conf':'/etc/nginx/events.conf','navigation.json':'/var/www/navigation.json',
'module-registry.json':'/var/www/module-registry.json',
'fs-campaign-dashboard.service':'/etc/systemd/system/fs-campaign-dashboard.service',
'fs-campaign-runtime.service':'/etc/systemd/system/fs-campaign-runtime.service',
'runtime.env':'/etc/fs-campaign-runtime.env'}}
RUNTIME_SPECIAL={{k:SPECIAL[k] for k in ('fs-campaign-runtime.service','runtime.env')}}
BACKEND_FILES={{'bridge.py'}}
def target(name):
 if name in SPECIAL:return SPECIAL[name]
 if name.startswith('app/') and '..' not in PurePosixPath(name).parts:return '/opt/fs-campaign-dashboard/'+name[4:]
 if name=='backend/bridge.py':return '/opt/fs-campaign-dashboard/'+name
 raise ValueError('outside fixture scope')
def validate(manifest,stage):
 assert set(SPECIAL).issubset(manifest['targets'])
 assert len(manifest['files'])==len(manifest['targets'])
 for row in manifest['files']:
  assert row['target']==target(row['candidate'])
  assert hashlib.sha256((stage/'candidate'/row['candidate']).read_bytes()).hexdigest()==row['sha256']
 return manifest['files']
'''


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.export, self.output = self.root / 'export', self.root / 'stage'
        self.export.mkdir()
        native = b'frozen fixture native\n'
        self.write('native/release_navigation_base.py', native)
        self.write('publish.py', FIXTURE_PUBLISHER.format(base_sha=package.sha(native)).encode())
        self.unit = b'[Unit]\r\nDescription=Original\r\n[Service]\r\nExecStart=/usr/local/bin/node /opt/server.mjs\r\n[Install]\r\nWantedBy=multi-user.target\r\n'
        self.write('fs-campaign-runtime.service', self.unit)
        self.base = {}
        self.baseline = dict(node_executable='/usr/local/bin/node', runtime_unit_exists=False,
            files={}, specials={}, guards={path: package.sha(path.encode()) for path in package.GUARDS})
        publisher = package.load_publisher(self.export)
        originals = {'navigation.json': b'{ "keep" : "original navigation bytes" }\n',
            'module-registry.json': b'{"keep":"original registry"}\r\n',
            'navigation.conf': b'# large unrelated management setup\nlocation /private/ { auth_request /existing; }\n',
            'fs-campaign-dashboard.service': self.unit}
        for name, raw in originals.items():
            self.baseline['specials'][publisher.target(name)] = dict(sha256=package.sha(raw),
                content_base64=base64.b64encode(raw).decode())
        for name in package.PUBLIC_REQUIRED | {'activity.js', 'assets/example.png', 'seasonal/assets/hero.webp'}:
            self.write('app/' + name, ('public ' + name).encode())
        self.write('app/runtime/server.mjs', b'runtime')
        self.write('backend/bridge.py', b'backend')
        self.commit = 'a' * 40

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, raw):
        path = self.export / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    def prepare(self):
        return package.prepare(self.export, self.baseline, self.commit, self.output, self.base)

    def manifest(self):
        return json.loads((self.output / 'approved-manifest.json').read_text())

    def test_package_unapproved_cas_guards_and_tools_are_not_install_targets(self):
        result = self.prepare()
        manifest = self.manifest()
        self.assertFalse(result['releaseReady'])
        self.assertFalse(manifest['releaseReady'])
        self.assertEqual(manifest['sourceRevision'], self.commit)
        self.assertEqual({r['path'] for r in manifest['unchangedRequired']}, package.GUARDS)
        self.assertEqual(result['approvedManifestSha256'], package.sha((self.output / 'approved-manifest.json').read_bytes()))
        self.assertTrue((self.output / 'publish.py').is_file())
        self.assertTrue((self.output / 'native/release_navigation_base.py').is_file())
        self.assertNotIn('publish.py', manifest['targets'])
        self.assertEqual(manifest['packagingToolsSha256']['publish.py'], package.sha((self.output / 'publish.py').read_bytes()))
        self.assertFalse(manifest['publicSnapshotRequiredAtPackageTime'])

    def test_preserve_navigation_and_management_nginx_original_bytes(self):
        self.prepare()
        publisher = package.load_publisher(self.export)
        for name in ('navigation.json', 'module-registry.json'):
            original = base64.b64decode(self.baseline['specials'][publisher.target(name)]['content_base64'])
            self.assertEqual((self.output / 'candidate' / name).read_bytes(), original)
        original = base64.b64decode(self.baseline['specials'][publisher.target('navigation.conf')]['content_base64'])
        nginx = (self.output / 'candidate/navigation.conf').read_bytes()
        self.assertEqual(nginx, original + package.NGINX_APPEND)
        self.assertIn(b'proxy_pass http://127.0.0.1:8949;', nginx)
        self.assertIn(b'proxy_set_header Cookie "";', nginx)
        self.assertEqual(nginx.count(b'location ^~ /events/'), 1)

    def test_service_revision_inserted_in_service_preserves_original_bytes(self):
        self.prepare()
        for name in ('fs-campaign-dashboard.service', 'fs-campaign-runtime.service'):
            unit = (self.output / 'candidate' / name).read_bytes()
            addition = b'Environment=CAMPAIGN_SOURCE_REVISION=' + self.commit.encode() + b'\r\n'
            self.assertEqual(unit.replace(addition, b''), self.unit)
            self.assertLess(unit.index(addition), unit.index(b'[Install]'))
        env = (self.output / 'candidate/runtime.env').read_text()
        for setting in ('CAMPAIGN_PUBLIC_MODE=preview', 'CAMPAIGN_PUBLIC_PREFIX=/events/',
                        'CAMPAIGN_PUBLIC_RELEASE=/var/lib/fs-campaign-public/current.json',
                        'CAMPAIGN_PUBLIC_MANIFEST=/opt/fs-campaign-dashboard/runtime/static-manifest.json',
                        'CAMPAIGN_PUBLIC_ORIGIN=https://47.85.224.112'):
            self.assertIn(setting, env)

    def test_static_manifest_exact_whitelist_excludes_internal_data_tests_and_nested_assets(self):
        for name in ('catalog.json', 'analytics/private.json', 'tests/test.cjs', 'docs/notes.md',
                     'assets/nested/hidden.png', 'raw.json'):
            self.write('app/' + name, b'private')
        self.prepare()
        static = json.loads((self.output / 'candidate/app/runtime/static-manifest.json').read_text())
        self.assertIn('seasonal/index.html', static)
        self.assertIn('seasonal/assets/hero.webp', static)
        self.assertNotIn('catalog.json', static)
        self.assertFalse(any('private' in name or 'nested' in name or name.startswith(('tests/', 'docs/')) for name in static))
        for name, digest in static.items():
            self.assertEqual(digest, package.sha((self.export / 'app' / name).read_bytes()))
        self.assertFalse((self.output / 'candidate/app/tests/test.cjs').exists())

    def test_changed_source_requires_matching_accepted_remote_base(self):
        name, target = 'app/activity.js', '/opt/fs-campaign-dashboard/activity.js'
        self.base[name] = package.sha(b'accepted')
        self.baseline['files'][target] = self.base[name]
        self.prepare()
        row = next(r for r in self.manifest()['files'] if r['candidate'] == name)
        self.assertEqual(row['beforeSha256'], self.base[name])

    def test_public_customization_rejected_with_exact_hashes(self):
        name, target = 'app/activity.js', '/opt/fs-campaign-dashboard/activity.js'
        self.base[name] = package.sha((self.export / name).read_bytes())
        self.baseline['files'][target] = package.sha(b'remote custom public')
        with self.assertRaisesRegex(ValueError, 'public customization.*remote=.*export='):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_unchanged_management_customization_preserved_while_modified_conflict_rejected(self):
        name, target = 'app/analytics/private.js', '/opt/fs-campaign-dashboard/analytics/private.js'
        self.write(name, b'accepted management')
        self.base[name] = package.sha(b'accepted management')
        self.baseline['files'][target] = package.sha(b'remote customization')
        self.prepare()
        self.assertFalse((self.output / 'candidate' / name).exists())
        self.assertIn(name, self.manifest()['skippedUnchangedFiles'])
        self.write(name, b'changed management')
        with self.assertRaisesRegex(ValueError, 'deployed customization'):
            package.prepare(self.export, self.baseline, self.commit, self.root / 'second-stage', self.base)

    def test_existing_equal_files_skip_and_new_backend_has_absent_cas(self):
        self.baseline['files']['/opt/fs-campaign-dashboard/activity.js'] = package.sha((self.export / 'app/activity.js').read_bytes())
        self.prepare()
        self.assertFalse((self.output / 'candidate/app/activity.js').exists())
        row = next(r for r in self.manifest()['files'] if r['candidate'] == 'backend/bridge.py')
        self.assertIsNone(row['beforeSha256'])

    def test_drifted_special_guard_node_or_existing_output_rejected(self):
        original = copy.deepcopy(self.baseline)
        for change in ('special', 'guard', 'node'):
            self.baseline = copy.deepcopy(original)
            if change == 'special':
                self.baseline['specials']['/var/www/navigation.json']['sha256'] = 'f' * 64
            elif change == 'guard':
                self.baseline['guards'] = {}
            else:
                self.baseline['node_executable'] = '/usr/bin/node'
            with self.assertRaises(ValueError):
                self.prepare()
        self.baseline = original
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError, 'new directory'):
            self.prepare()

    def test_existing_events_or_wrong_unit_node_never_silently_replaced(self):
        with self.assertRaisesRegex(ValueError, 'actual /usr/local/bin/node'):
            package.service_revision(self.unit.replace(b'/usr/local/bin/node', b'/usr/bin/node'), self.commit)
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            package.service_revision(package.service_revision(self.unit, self.commit), self.commit)
        target = '/etc/nginx/events.conf'
        raw = b'location /events/ { return 404; }\n'
        self.baseline['specials'][target] = dict(sha256=package.sha(raw), content_base64=base64.b64encode(raw).decode())
        with self.assertRaisesRegex(ValueError, 'events location'):
            self.prepare()


if __name__ == '__main__':
    unittest.main()
