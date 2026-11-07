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
            bundle=Path(folder)/'node.zip';builder.build(bundle)
            with zipfile.ZipFile(bundle) as archive:
                self.assertEqual(hashlib.sha256(archive.read('manifest.json')).hexdigest(),release.WORKER)

    def fixture(self, folder, *, extra_change=False):
        release=load('update_collection_bidirectional');builder=load('build_collection_node')
        root=Path(folder)/'role';stage=Path(folder)/'stage';stage.mkdir();(root/'code').mkdir(parents=True)
        spool=Path(folder)/'spool';spool.mkdir()
        candidate=stage/'new.zip';builder.build(candidate)
        with zipfile.ZipFile(candidate) as archive:current={name:archive.read(name) for name in archive.namelist()}
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
