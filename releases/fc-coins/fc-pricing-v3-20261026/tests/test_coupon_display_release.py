"""Coupon display ships one explicit root source without widening old scopes."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

DEPLOY=Path(__file__).resolve().parents[1]/'deploy'
ROOT=DEPLOY.parents[3]
sys.path.insert(0,str(DEPLOY))
import build_stage
import fc_v3_release_adapter as adapter
import prepare_manifest as prepare
import target_map


class CouponDisplayRelease(unittest.TestCase):
    def test_scope_is_five_existing_targets_and_keeps_original_101_and_old_scopes(self):
        expected={'source/storefront_monitor.py':'/opt/fc27-cloud-browser/storefront_monitor.py'}
        expected.update({prefix+'fc_pricing_v3/'+name:root+'/fc_pricing_v3/'+name
                         for prefix,root in [('source/','/opt/fc27-cloud-browser'),('source/hermes-copy/','/opt/fs-hermes-fc')]
                         for name in ('smart.py','runtime.py')})
        self.assertEqual(target_map.COUPON_DISPLAY_SCOPE,'fc-pricing-v3-coupon-display-20261109')
        self.assertEqual(adapter.COUPON_DISPLAY_TARGETS,expected)
        self.assertEqual(set(target_map.COUPON_DISPLAY_NAMES),set(expected))
        self.assertEqual(len(adapter.TARGETS),101);self.assertEqual(target_map.TARGET_COUNT,101)
        self.assertNotIn('source/storefront_monitor.py',adapter.TARGETS)
        for mapping,count in [(adapter.QUOTE_FRAGMENT_TARGETS,2),(adapter.QUOTE_PREVIEW_TARGETS,3),
                              (adapter.REPAIR_TARGETS,4),(adapter.BIDIRECTIONAL_TARGETS,25)]:self.assertEqual(len(mapping),count)
        value=dict(scope=target_map.COUPON_DISPLAY_SCOPE,businessWrites=False,timersChanged=False,releaseReady=True,
                   files=[dict(candidate=n,target=t,beforeSha256='a'*64,sha256='b'*64,owner='0:0',mode='0o644') for n,t in expected.items()])
        self.assertEqual(adapter.checked_manifest(value),value)
        for change in ('missing','new','writer','businessWrites','timersChanged'):
            changed=json.loads(json.dumps(value))
            if change=='missing':changed['files'].pop()
            elif change=='new':changed['files'][0]['beforeSha256']=None
            elif change=='writer':changed['files'][0].update(candidate='source/price_writer.py',target='/opt/fc27-cloud-browser/price_writer.py')
            else:changed[change]=True
            with self.subTest(change=change),self.assertRaises(ValueError):adapter.checked_manifest(changed)

    def test_builder_adds_only_explicit_git_root_monitor_in_coupon_mode(self):
        def blob(checkout,path):return path.read_bytes().replace(b'\r\n',b'\n')
        def git(command,**kwargs):return 'a'*40 if command[1]=='rev-parse' else ''
        with tempfile.TemporaryDirectory() as folder,patch.object(build_stage,'git_blob',side_effect=blob) as read, \
                patch.object(build_stage.subprocess,'check_output',side_effect=git):
            checkout=Path(folder)/'checkout'
            release=checkout/'releases/fc-coins/fc-pricing-v3-20261026'
            for name in target_map.targets(DEPLOY.parent/'source'):
                source=release/'source'/name.removeprefix('hermes-copy/')
                source.parent.mkdir(parents=True,exist_ok=True)
                source.write_bytes(b'#!/bin/sh\n# source fixture\n' if source.suffix=='.sh' else b'# source fixture\n')
            for name in ('target_map.py','release_navigation_base.py','fc_v3_release_adapter.py','prepare_manifest.py','release_readiness.py'):
                file=release/'deploy'/name;file.parent.mkdir(exist_ok=True);file.write_bytes((DEPLOY/name).read_bytes())
            monitor_source=checkout/'fc27_cloud_browser/storefront_monitor.py'
            monitor_source.parent.mkdir();monitor_source.write_bytes(b'# canonical Git root monitor fixture\n')
            for coupon in (False,True):
                with self.subTest(coupon=coupon):
                    archive=Path(folder)/('coupon.tar.gz' if coupon else 'default.tar.gz')
                    result=build_stage.build(checkout,archive,coupon_display=coupon)
                    with tarfile.open(archive,'r:gz') as bundle:
                        base='fc-pricing-v3-20261026/'
                        manifest=json.load(bundle.extractfile(base+'source-manifest.json'))
                        self.assertEqual(len(manifest['files']),102 if coupon else 101)
                        self.assertEqual(result['targets'],102 if coupon else 101)
                        monitor=base+'candidate/source/storefront_monitor.py'
                        if coupon:
                            raw=bundle.extractfile(monitor).read()
                            self.assertEqual(raw,blob(checkout,monitor_source))
                            self.assertEqual(hashlib.sha256(raw).hexdigest(),manifest['files']['source/storefront_monitor.py'])
                            self.assertTrue(any(c.args==(checkout.resolve(),monitor_source.resolve()) for c in read.call_args_list))
                        else:self.assertNotIn(monitor,bundle.getnames())

    def test_coupon_builder_refuses_uncommitted_root_monitor(self):
        def git(command,**kwargs):
            if command[1]=='rev-parse':return 'a'*40
            self.assertIn('fc27_cloud_browser/storefront_monitor.py',command)
            return ' M fc27_cloud_browser/storefront_monitor.py'
        with tempfile.TemporaryDirectory() as folder,patch.object(build_stage.subprocess,'check_output',side_effect=git):
            with self.assertRaisesRegex(ValueError,'source_tree_has_uncommitted_changes'):
                build_stage.build(ROOT,Path(folder)/'unsafe.tar.gz',coupon_display=True)

    def test_coupon_prepare_selects_five_and_protects_pricing_source_and_collection_role(self):
        with tempfile.TemporaryDirectory() as folder:
            stage=Path(folder);deploy=stage/'deploy';deploy.mkdir()
            selected=target_map.COUPON_DISPLAY_NAMES
            names=list(selected)+['source/pricing_sources.py']
            mapping={};extra={}
            for index,name in enumerate(names):
                candidate=stage/'candidate'/name;candidate.parent.mkdir(parents=True,exist_ok=True);candidate.write_bytes(name.encode())
                live=stage/'live'/str(index);live.parent.mkdir(exist_ok=True);live.write_bytes(('old:'+name).encode())
                if name=='source/storefront_monitor.py':extra[name]=str(live)
                else:mapping[name.removeprefix('source/')]=str(live)
            sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'a'*64
            provenance=dict(sourceCommit='a'*40,files={n:sha(stage/'candidate'/n) for n in names})
            provenance['repositorySources']={'source/storefront_monitor.py':target_map.COUPON_DISPLAY_SOURCE}
            (stage/'source-manifest.json').write_text(json.dumps(provenance))
            base=SimpleNamespace(HERMES_TARGETS={},HERMES_CAPABILITY_TARGETS={},CAP_PROTECTED_SESSION=set(),HERMES_DIRECT_TARGETS={})
            inspect=Mock(return_value={'ok':True})
            with patch.object(prepare,'STAGE',stage),patch.object(prepare,'HERE',deploy),patch.object(prepare,'targets',return_value=mapping), \
                 patch.object(prepare,'TARGET_COUNT',len(mapping)),patch.object(prepare,'COUPON_DISPLAY_EXTRA',extra), \
                 patch.object(prepare,'regular'),patch.object(prepare,'sha',side_effect=sha),patch.object(prepare,'load_base',return_value=base), \
                 patch.object(adapter,'load_base',return_value=SimpleNamespace(inspect=inspect)), \
                 patch.object(prepare.subprocess,'check_output',return_value='ActiveState=active'):
                result=prepare.prepare(coupon_display=True)
                manifest=json.loads((stage/'approved-manifest.json').read_text())
                self.assertEqual(result['files'],5);self.assertEqual(result['new'],0)
                self.assertEqual({r['candidate'] for r in manifest['files']},set(selected))
                protected={r['path'] for r in manifest['unchangedRequired']}
                self.assertIn(mapping['pricing_sources.py'],protected)
                self.assertTrue(set(target_map.COUPON_DISPLAY_PROTECTED).issubset(protected))
                self.assertEqual((stage/'approved-manifest.json').read_bytes(),(deploy/'approved-manifest.json').read_bytes())
                inspect.assert_called_once_with(manifest,stage)
                provenance['repositorySources']['source/storefront_monitor.py']='wrong/storefront_monitor.py'
                (stage/'source-manifest.json').write_text(json.dumps(provenance))
                with self.assertRaisesRegex(ValueError,'coupon_display_repository_source_changed'):prepare.prepare(coupon_display=True)
                provenance['repositorySources']['source/storefront_monitor.py']=target_map.COUPON_DISPLAY_SOURCE
                (stage/'source-manifest.json').write_text(json.dumps(provenance))
                (stage/'candidate/source/storefront_monitor.py').write_bytes(b'changed after git stage')
                with self.assertRaisesRegex(ValueError,'staged_payload_differs_from_git_source_manifest'):prepare.prepare(coupon_display=True)

    def test_coupon_scope_keeps_shared_model_fences_and_original_quiescent_check(self):
        load=next(n for n in ast.parse((DEPLOY/'fc_v3_release_adapter.py').read_text('utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='load_base')
        branch=next(n for n in load.body if isinstance(n,ast.If) and any(isinstance(v,ast.Attribute) and v.attr=='hermes_admission_fence' for v in ast.walk(n)))
        original=Mock();base=SimpleNamespace(hermes_admission_fence=original,model_release_lock=original)
        namespace=dict(scope=target_map.COUPON_DISPLAY_SCOPE,COLLECTION_SCOPE=target_map.COLLECTION_SCOPE,base=base,
                       original_quiescent=Mock(side_effect=ValueError('original_model_not_idle')))
        quiet=next(n for n in load.body if isinstance(n,ast.FunctionDef) and n.name=='quiescent')
        exec(compile(ast.Module(body=[branch,quiet],type_ignores=[]),'coupon-fence-contract','exec'),namespace)
        self.assertIs(base.hermes_admission_fence,original);self.assertIs(base.model_release_lock,original)
        with self.assertRaisesRegex(ValueError,'original_model_not_idle'):namespace['quiescent'](Path('/'))

    def test_preparer_and_builder_coupon_modes_are_explicit_and_exclusive(self):
        for script in ('prepare_manifest.py','build_stage.py'):
            result=subprocess.run([sys.executable,'-B',str(DEPLOY/script),'--help'],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn('--coupon-display',result.stdout)
        result=subprocess.run([sys.executable,'-B',str(DEPLOY/'prepare_manifest.py'),'--coupon-display','--collection'],capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)


if __name__=='__main__':unittest.main()
