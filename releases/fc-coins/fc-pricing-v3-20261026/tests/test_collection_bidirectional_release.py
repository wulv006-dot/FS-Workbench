from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'deploy'/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class BidirectionalRoleRelease(unittest.TestCase):
    def test_role_boundaries_and_manifest_digest_match_the_current_candidate(self):
        release=load('update_collection_bidirectional');builder=load('build_collection_node')
        common={'fc_collection/'+name for name in ('contracts.py','public_sources.py','adapters.py','worker.py')}|{'manifest.json'}
        self.assertEqual(release.CHANGED,dict(node=common,control=common|{'fc_collection/client.py'}))
        self.assertEqual(release.OLD,dict(node='55eeff178d37e4747c1fe5b4f3d49b9a258b4d5cf7eeb75a6cbf6493cba5b14d',
            control='53e1e8fa7719d57e35a7dc33a200948827ef06e8479e70922379479834f913ec'))
        with tempfile.TemporaryDirectory() as folder:
            # The current builder intentionally includes Lootbar. Historical pins bind
            # the original ea496e2 Git bytes, not whatever the current builder emits.
            raw=(ROOT/'tests/fixtures/collection-node-20261107.json').read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),release.WORKER)
            self.assertEqual(json.loads(raw)['sources'],['ArabUT'])

    def fixture(self, folder, *, extra_change=False):
        release=load('update_collection_bidirectional');builder=load('build_collection_node')
        root=Path(folder)/'role';stage=Path(folder)/'stage';stage.mkdir();(root/'code').mkdir(parents=True)
        spool=Path(folder)/'spool';spool.mkdir()
        candidate=stage/'new.zip'
        old_manifest=json.loads((ROOT/'tests/fixtures/collection-node-20261107.json').read_text())
        current={name:('# new fixture '+name+'\n').encode() for name in old_manifest['sha256']}
        manifest=dict(old_manifest,sha256={n:hashlib.sha256(b).hexdigest() for n,b in current.items()})
        current['manifest.json']=json.dumps(manifest).encode()
        with zipfile.ZipFile(candidate,'w') as archive:
            for name,body in current.items():archive.writestr(name,body)
        previous=current.copy()
        changed=release.CHANGED['node']-{'manifest.json'}
        for name in changed|({'fc_collection/protocol.py'} if extra_change else set()):previous[name]=b'# original fixture\n'
        manifest=json.loads(previous['manifest.json']);manifest['sha256']={name:hashlib.sha256(body).hexdigest() for name,body in previous.items() if name!='manifest.json'}
        previous['manifest.json']=json.dumps(manifest).encode()
        old=stage/release.OLD_NAMES['node']
        with zipfile.ZipFile(old,'w') as archive:
            for name,body in previous.items():archive.writestr(name,body)
        for name,body in previous.items():
            target=root/'code'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(body)
        release.STAGE=stage;release.OLD=dict(node=hashlib.sha256(old.read_bytes()).hexdigest());release.NEW=dict(node=hashlib.sha256(candidate.read_bytes()).hexdigest())
        release.WORKER=hashlib.sha256(current['manifest.json']).hexdigest()
        original_stat=Path.stat
        def stat_(path,*args,**kwargs):
            values=list(original_stat(path,*args,**kwargs));values[4]=0;return os.stat_result(values)
        def path_(value):return root if str(value)=='/opt/fs-fc-collector' else spool if str(value)=='/var/lib/fs-fc-collector/spool' else Path(value)
        return release,root,candidate,path_,stat_

    def test_preview_is_read_only_and_rejects_stale_CAS_or_existing_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            release,root,candidate,path_,stat_=self.fixture(folder)
            before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(release,'Path',side_effect=path_), patch.object(release.os,'geteuid',return_value=0,create=True), \
                    patch.object(release.socket,'gethostname',return_value='FSHTUS01'),patch.object(Path,'stat',stat_), \
                    patch.object(release.subprocess,'run') as process,patch.object(release,'atomic') as atomic:
                result=release.update(candidate,release.NEW['node'],release.WORKER,False)
                self.assertEqual(result['phase'],'preview');process.assert_not_called();atomic.assert_not_called()
                (root/'code-before-bidirectional-20261107').mkdir()
                with self.assertRaises(AssertionError):release.update(candidate,release.NEW['node'],release.WORKER,False)
                (root/'code-before-bidirectional-20261107').rmdir()
                (root/'code/fc_collection/contracts.py').write_bytes(b'concurrent change')
                with self.assertRaises(AssertionError):release.update(candidate,release.NEW['node'],release.WORKER,False)
            after={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(after.keys(),before.keys())
            self.assertTrue(all(value==after[name] for name,value in before.items() if name!='code/fc_collection/contracts.py'))

    def test_valid_bundles_cannot_modify_unlisted_modules(self):
        with tempfile.TemporaryDirectory() as folder:
            release,root,candidate,path_,stat_=self.fixture(folder,extra_change=True)
            with patch.object(release,'Path',side_effect=path_),patch.object(release.os,'geteuid',return_value=0,create=True), \
                    patch.object(release.socket,'gethostname',return_value='FSHTUS01'),self.assertRaises(AssertionError):
                release.update(candidate,release.NEW['node'],release.WORKER,False)


class ArabUTActiveQuoteRelease(unittest.TestCase):
    CHANGED = {
        'fc_collection/adapters.py',
        'fc_collection/contracts.py',
        'fc_collection/public_sources.py',
    }

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.stage = Path(folder.name)
        self.release = load('update_collection_bidirectional')
        self.node = self.make_role('node')
        self.control = self.make_role('control')
        self.access = self.stage / 'access.json'
        self.access.write_text(json.dumps(dict(worker_digest=self.node.installed, role='fixture')))
        self.access.chmod(0o600)
        self.release.LOOTBAR_ACCESS = self.access
        self.release.LOOTBAR_SPOOL = self.stage / 'spool'
        self.release.LOOTBAR_SPOOL.mkdir()
        patches = ExitStack()
        self.addCleanup(patches.close)
        patches.enter_context(patch.object(self.release, '_lootbar_access_read', side_effect=self.access.read_bytes))
        patches.enter_context(patch.object(self.release, '_lootbar_root_owned', return_value=True))
        patches.enter_context(patch.object(self.release, 'ARAB_ACTIVE_QUOTE_BEFORE_MANIFEST',
                                          {'node': self.node.installed, 'control': self.control.installed}))

    def make_role(self, role):
        root = self.stage / role
        code = root / 'code'
        code.mkdir(parents=True)
        protected = root / 'protected'
        protected.write_bytes(b'unmodified')
        self.release.LOOTBAR_ROOTS[role] = root
        self.release.LOOTBAR_ROLE_PROTECTED[role] = (str(protected),)
        files = {
            name: f'# previous {name}\n'.encode()
            for name in self.release.LOOTBAR_ROLE_FILES[role] - {'manifest.json'}
        }

        def manifest(files):
            return json.dumps(dict(
                schema_version=1, role='limited_fc_collector' if role == 'node' else 'fc_collection_controller',
                sources=['ArabUT', 'Lootbar'], credentials=[], production_consume=False, business_runtime=False,
                sha256={name: hashlib.sha256(body).hexdigest() for name, body in files.items()},
            ), sort_keys=True).encode()

        old_manifest = manifest(files)
        for name, body in dict(files, **{'manifest.json': old_manifest}).items():
            target = code / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        return SimpleNamespace(role=role, root=root, files=files, manifest=manifest,
                               installed=hashlib.sha256(old_manifest).hexdigest())

    def prepare(self, fixture, changes=CHANGED, **kwargs):
        files = dict(fixture.files)
        files.update({name: b'# repaired quote\n' for name in changes})
        manifest = fixture.manifest(files)
        target = self.stage / f'{fixture.role}.zip'
        with zipfile.ZipFile(target, 'w') as archive:
            for name, body in dict(files, **{'manifest.json': manifest}).items():
                archive.writestr(name, body)
        if fixture.role == 'node':
            self.next_worker = hashlib.sha256(manifest).hexdigest()
        return self.release.prepare_lootbar(
            fixture.role, target, hashlib.sha256(target.read_bytes()).hexdigest(),
            'fixture', 'a' * 40, worker_digest=self.next_worker, arabut_active_quote=True, **kwargs,
        )

    def preview(self, manifest):
        path = self.stage / f"{manifest['role']}.json"
        raw = json.dumps(manifest).encode()
        path.write_bytes(raw)
        return self.release.update_lootbar(path, manifest_sha256=hashlib.sha256(raw).hexdigest())

    def test_node_and_controller_can_preview_exact_active_quote_release(self):
        node = self.prepare(self.node)
        control = self.prepare(self.control)
        for manifest in (node, control):
            with self.subTest(role=manifest['role']):
                self.assertEqual(manifest['scope'], 'fc-arabut-active-quote-20261119')
                self.assertEqual({name for name, old in manifest['before'].items()
                                  if old != manifest['after'][name]}, self.CHANGED | {'manifest.json'})
                self.assertEqual(self.preview(manifest)['phase'], 'preview')
        self.assertEqual(control['old_worker_digest'], self.node.installed)
        self.assertEqual(control['worker_digest'], node['after']['manifest.json'])
        self.assertEqual(json.loads(self.access.read_text())['worker_digest'], self.node.installed)

    def test_new_scope_rejects_extra_files_and_missing_required_changes(self):
        with self.assertRaisesRegex(ValueError, 'arab_active_quote_exact_change_scope'):
            self.prepare(self.node, self.CHANGED - {'fc_collection/contracts.py'})
        with self.assertRaisesRegex(ValueError, 'arab_active_quote_exact_change_scope'):
            self.prepare(self.control, self.CHANGED | {'fc_collection/client.py'})

    def test_manifest_and_access_predecessors_remain_pinned(self):
        with self.assertRaisesRegex(ValueError, 'arab_active_quote_pinned_role_required'):
            self.prepare(self.node, installed_manifest=self.node.installed)
        node = self.prepare(self.node)
        bad_base = dict(node['before'], **{'manifest.json': '2' * 64})
        with self.assertRaisesRegex(ValueError, 'lootbar_original_manifest_drift'):
            self.preview(dict(node, before=bad_base))
        with self.assertRaisesRegex(ValueError, 'lootbar_new_worker_digest_required'):
            self.preview(dict(node, worker_digest='2' * 64))
        control = self.prepare(self.control)
        with self.assertRaisesRegex(ValueError, 'lootbar_worker_digest_drift'):
            self.preview(dict(control, old_worker_digest='2' * 64))
        self.access.write_text(json.dumps(dict(worker_digest=self.node.installed, role='changed')))
        with self.assertRaisesRegex(ValueError, 'lootbar_access_cas_drift'):
            self.preview(control)
