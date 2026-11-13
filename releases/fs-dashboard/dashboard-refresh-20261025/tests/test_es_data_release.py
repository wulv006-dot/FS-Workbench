import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'deploy'))
import es_data_release as release
import prepare_es_data as prep


class ESRelease(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.captured = self.folder/'captured'
        self.captured.mkdir()
        self.stage = self.folder/'stage'
        self.source_commit = 'a'*40
        self.sources = {path:b'# original\n' for path in prep.SOURCES.values()}
        self.desired = {path:b'# ES candidate\n' for path in prep.SOURCES.values()}
        routes = b'# unrelated route\r\n' + b''.join(
            f'location = {prep.LOCATIONS[n]} {{\r\n    auth_request /original;\r\n    alias {prep.STATIC_OLD[n]};\r\n}}\r\n'.encode()
            for n in release.UI)
        (self.captured/'routes.conf').write_bytes(routes)
        self.baseline = {release.FORMAL:prep.digest(routes),**{name:'b'*64 for name in release.PROTECTED}}
        for name,target in release.targets('admin-es-20261113-000000000000').items():
            if name not in release.NEW and name in prep.SOURCES:
                self.baseline[target] = prep.digest(self.sources[prep.SOURCES[name]])
        for name,target in prep.STATIC_OLD.items():
            raw = self.sources[prep.SOURCES['ui/'+name]]
            (self.captured/name).write_bytes(raw)
            self.baseline[target] = prep.digest(raw)
        publisher = ROOT.parent/'order-email-export-20261111/publisher'
        self.delegate = (publisher/'adapter.py').read_bytes().replace(b'\r\n',b'\n')
        self.frozen = self.folder/'publisher.py'
        self.frozen.write_bytes((publisher/'frozen_base.py').read_bytes().replace(b'\r\n',b'\n'))

    def source(self, revision, relative):
        if relative == prep.EMAIL_ADAPTER:
            return self.delegate
        return (self.sources if revision == prep.BASE else self.desired)[relative]

    def build(self):
        return prep.build(self.source,self.source_commit,self.baseline,self.captured,self.stage,frozen_base=self.frozen)

    def test_real_publisher_checks_exact_stage_and_only_six_route_aliases_change(self):
        manifest = self.build()
        self.assertEqual(len(manifest['files']),24)
        self.assertFalse(manifest['releaseReady'])
        base = release.publisher(self.stage,manifest,frozen_base=self.frozen)
        self.assertEqual(len(base.validate(manifest,self.stage)),24)
        routes = (self.stage/'candidate/routes.conf').read_bytes()
        for name, old in prep.STATIC_OLD.items():
            routes = routes.replace((release.STATIC+manifest['assetVersion']+'/'+name).encode(),old.encode())
        self.assertEqual(routes,(self.captured/'routes.conf').read_bytes())
        for change in (lambda m:m['files'][0].update(target='/tmp/other'),
                       lambda m:m['files'][0].update(beforeSha256=None),
                       lambda m:m['unchangedRequired'].pop(), lambda m:m.update(timersChanged=True)):
            bad=copy.deepcopy(manifest);change(bad)
            with self.assertRaises(ValueError):base.validate(bad,self.stage)
        path = self.stage/'candidate/range/local_repeat_source.py'
        path.write_bytes(b'# tampered')
        with self.assertRaisesRegex(ValueError,'staged payload differs'):base.validate(manifest,self.stage)

    def test_missing_capture_and_changed_route_cannot_stage(self):
        self.baseline.pop(prep.STATIC_OLD['business.js'])
        with self.assertRaises(KeyError):self.build()
        self.baseline[prep.STATIC_OLD['business.js']]=prep.digest((self.captured/'business.js').read_bytes())
        path = self.captured/'routes.conf'
        path.write_bytes(path.read_bytes().replace(b'auth_request /original;',b'auth_request /changed;'))
        with self.assertRaisesRegex(ValueError,'captured formal route hash differs'):self.build()
        self.assertFalse(self.stage.exists())

    def test_merges_only_reviewed_conflicts_and_keeps_live_store_without_index(self):
        conflicts = list(prep.REVIEWED_CONFLICTS.items())
        current = ("            if target == current and start is not None:\n                return ['current']\n"
                   +prep.INDEX_BRANCH+'            if bounded_only:\n                return None\n')
        conflicts.append(('user_store.py',('',current)))
        for name,(live,desired) in conflicts:
            conflict = ('<<<<<<< candidate\n'+desired+'=======\n'+live+'>>>>>>> live\n').encode()
            if name=='user_store.py':
                conflict = b'        target = int(version)\n        result = {}\n'+conflict+prep.REPLAY_RANGE.encode()
            with self.subTest(name=name),patch.object(prep.subprocess,'run',return_value=Mock(returncode=1,stdout=conflict)):
                output = prep.compose(name,b'base',b'candidate',b'production')
                self.assertNotIn(b'<<<<<<<',output)
                if name=='user_store.py':
                    self.assertNotIn(b'user_version_index',output)
                    self.assertIn(b'if bounded_only',output)
                    self.assertEqual(output.count(prep.REPLAY_RANGE.encode()),1)
                    self.assertLess(output.index(prep.REPLAY_RANGE.encode()),output.index(b'if target == current'))
                else:
                    self.assertIn(desired.encode(),output)
                    self.assertIn(live.splitlines()[0].encode(),output)
                with self.assertRaisesRegex(ValueError,'unresolved source drift'):
                    prep.compose('unrelated.py',b'base',b'candidate',b'production')

    def test_static_merge_is_content_addressed_using_retained_live_delta(self):
        path = self.captured/'legacy-business.js'
        path.write_bytes(b'# retained live delta\n')
        self.baseline[prep.STATIC_OLD[path.name]]=prep.digest(path.read_bytes())
        with patch.object(prep,'compose',side_effect=lambda n,b,d,l:l if n==path.name else d):
            manifest=self.build()
        staged=(self.stage/'candidate/ui/legacy-business.js').read_bytes()
        self.assertEqual(staged,path.read_bytes())
        content=b''.join(name.encode()+b'\0'+(self.stage/'candidate/ui'/name).read_bytes() for name in release.UI)
        self.assertTrue(manifest['assetVersion'].endswith(hashlib.sha256(content).hexdigest()[:12]))

    def test_delta_preserves_live_code_and_rewrites_only_summary_aliases(self):
        baseline = {target:'b'*64 for target in release.DELTA_PROTECTED}
        routes = b'# live SEO route\r\n' + b''.join(
            f'location = {prep.DELTA_LOCATIONS[n]} {{\r\n    auth_request /original;\r\n    alias {prep.DELTA_STATIC_OLD[n]};\r\n}}\r\n'.encode()
            for n in release.DELTA_UI)
        (self.captured/'routes.conf').write_bytes(routes)
        baseline[release.FORMAL] = prep.digest(routes)
        base = b'def delivery_timestamp(value):\n    return value\n\ndef main():\n    pass\n'
        desired = b'def delivery_timestamps(value):\n    return value, None\n\ndef main():\n    pass\n'
        for name,target in release.DELTA_CODE.items():
            leaf = Path(name).name
            live = b'# unchanged lxml initialization\n'+base if leaf=='channel_cost_source.py' else b'# original\n'
            (self.captured/leaf).write_bytes(live)
            baseline[target] = prep.digest(live)
        for name,target in prep.DELTA_STATIC_OLD.items():
            live = b'// live-only boot sequence\nconst mismatch = '+prep.SUMMARY_V2_GUARD+b';\n'
            (self.captured/name).write_bytes(live)
            baseline[target] = prep.digest(live)

        def source(revision, relative):
            if relative == prep.EMAIL_ADAPTER:
                return self.delegate
            if relative.endswith('.js'):
                return prep.SUMMARY_COMPAT_GUARD
            if relative.endswith('channel_cost_source.py'):
                return base if revision==prep.DEPLOYED else desired
            return b'# original\n' if revision==prep.DEPLOYED else b'# updated\n'

        manifest = prep.build_delta(source,self.source_commit,baseline,self.captured,self.stage,frozen_base=self.frozen)
        self.assertEqual(len(manifest['files']),11)
        self.assertFalse(manifest['releaseReady'])
        writer = release.publisher(self.stage,manifest,frozen_base=self.frozen)
        self.assertEqual(len(writer.validate(manifest,self.stage)),11)
        candidate = self.stage/'candidate'
        patched = (candidate/'routes.conf').read_bytes()
        for name,old in prep.DELTA_STATIC_OLD.items():
            patched = patched.replace((release.STATIC+manifest['assetVersion']+'/'+name).encode(),old.encode())
            self.assertEqual((candidate/'ui'/name).read_bytes(),
                (self.captured/name).read_bytes().replace(prep.SUMMARY_V2_GUARD,prep.SUMMARY_COMPAT_GUARD))
        self.assertEqual(patched,routes)
        self.assertEqual((candidate/'host/channel_cost_source.py').read_bytes(),b'# unchanged lxml initialization\n'+desired)
        for row in manifest['files']:
            if row['candidate'] in release.DELTA_CODE:
                self.assertEqual(row['beforeSha256'],baseline[row['target']])
        invalid = copy.deepcopy(manifest)
        invalid['files'][1]['beforeSha256'] = None
        with self.assertRaisesRegex(ValueError,'before CAS'):
            writer.validate(invalid,self.stage)
