"""Exact three-platform code release; old scopes and their 101-file stage stay fixed."""
import hashlib
import ast
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

DEPLOY = Path(__file__).resolve().parents[1] / 'deploy'
ROOT = DEPLOY.parents[3]
sys.path.insert(0, str(DEPLOY))
import build_stage
import fc_v3_release_adapter as adapter
import prepare_manifest as prepare
import target_map


class ThreePlatformRelease(unittest.TestCase):
    def test_actual_adapter_guard_restart_and_rollback_keep_off_config_without_old_pid_gate(self):
        text=(DEPLOY/'fc_v3_release_adapter.py').read_text('utf-8')
        load=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='load_base')
        functions=[n for n in load.body if isinstance(n,ast.FunctionDef) and n.name in ('guards','restart')]
        body=ast.parse("holding_fc_locks=True\nbundle_release_state=dict(holding=True,admitted=True,phase='before')").body+functions
        body+=ast.parse('return guards,restart,bundle_release_state').body
        factory=ast.FunctionDef(name='factory',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),body=body,decorator_list=[])
        namespace=dict(scope=target_map.THREE_PLATFORM_SCOPE,THREE_PLATFORM_SCOPE=target_map.THREE_PLATFORM_SCOPE,
            base=None,original_guards=Mock(),fc_release_quiescent=Mock(return_value=True),
            fc=SimpleNamespace(tick=None,api=None),Path=Path,hashlib=hashlib,subprocess=SimpleNamespace(run=Mock()),
            restart_with_hermes_readiness=Mock(),original_restart=Mock(),bundle_readiness=adapter.bundle_readiness,
            bundle_bootstrap_guard=adapter.bundle_bootstrap_guard)
        for name in ('HISTORY_READ_SCOPE','SCOPE','DELTA_SCOPE','SHADOW_SCOPE','OPERATING_SCOPE','COLLECTION_SCOPE','BIDIRECTIONAL_SCOPE','REPAIR_SCOPE','QUOTE_FRAGMENT_SCOPE','QUOTE_PREVIEW_SCOPE','DAILY_REPAIR_SCOPE','DAILY_SUMMARY_SCOPE','COUPON_DISPLAY_SCOPE','LOOTBAR_CALLER_SCOPE'):
            namespace[name]=getattr(adapter,name)
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'server.py';file.write_bytes(b'old')
            before=dict(revision=1,settings=dict(write_enabled=True,write_auto=True),bundles=[])
            off=dict(before,revision=2,settings=dict(write_enabled=False,write_auto=False))
            process=dict(pid=100,threads=[dict(tid=100,start_ticks=1000,scheduler_sleep=False),dict(tid=101,start_ticks=1002,scheduler_sleep=True)])
            legacy=dict(revision=2,settings=off['settings'],write=dict(enabled=False,auto=False),bundles=[],last_refresh=dict(status='ok'))
            current=dict(config=off,state=legacy,process=process)
            class File:
                def read_bytes(self):return file.read_bytes()
                def exists(self):return file.exists()
                def is_file(self):return file.is_file()
                def stat(self):return SimpleNamespace(st_uid=0,st_gid=0,st_mode=0o100644)
            namespace['base']=SimpleNamespace(rooted=lambda root,p:File())
            with patch.object(adapter,'bundle_live_snapshot',side_effect=lambda **kw:(current['config'],current['state'],current['process'])), \
                 patch.object(adapter,'BUNDLE_SOURCE',file),patch.object(adapter,'bundle_state',side_effect=lambda:current['state']):
                proof=adapter.capture_bundle_bootstrap(dict(config=before,pid=100,processStartTicks=1000,schedulerTid=101,schedulerStartTicks=1002))
                manifest=dict(scope=target_map.THREE_PLATFORM_SCOPE,bundleBootstrap=proof,files=[dict(
                    candidate='source/pack_bundles_server.py',target=str(file),mode='0o644',
                    beforeSha256=hashlib.sha256(b'old').hexdigest(),sha256=hashlib.sha256(b'new').hexdigest())])
                exec(compile(ast.fix_missing_locations(ast.Module(body=[factory],type_ignores=[])),'actual-adapter-sequence','exec'),namespace)
                guards,restart,phase=namespace['factory']()
                guards(manifest,Path('/'))
                file.write_bytes(b'new');guards(manifest,Path('/'))
                def reboot(command,**kw):
                    if command==['systemctl','restart','fc27-pack-bundles.service']:
                        current['process']=dict(pid=200,threads=[])
                        current['state']=dict(legacy,price_scope_contract='fc27_three_platform_v1',write_admission_contract='bundle_write_admission_v1') if file.read_bytes()==b'new' else legacy
                namespace['subprocess'].run.side_effect=reboot
                restart(manifest);self.assertEqual(phase['phase'],'new')
                guards(manifest,Path('/'))  # even if the original base later adds a post-restart guard
                file.write_bytes(b'old');restart(manifest)
                self.assertEqual(phase['phase'],'rollback');guards(manifest,Path('/'))
                self.assertEqual(current['config'],off)

    def test_bootstrap_proof_covers_exact_off_config_threads_and_postrestart_rollback_stages(self):
        self.assertTrue(hasattr(adapter,'bundle_bootstrap_guard'))
        before=dict(revision=7,settings=dict(write_enabled=True,write_auto=True,interval_hours=1),bundles=[])
        off=json.loads(json.dumps(before));off['revision']=8
        off['settings'].update(write_enabled=False,write_auto=False)
        baseline=dict(config=before,pid=100,processStartTicks=1000,schedulerTid=101,schedulerStartTicks=1002)
        process=dict(pid=100,threads=[dict(tid=100,start_ticks=1000,scheduler_sleep=False),
                                      dict(tid=101,start_ticks=1002,scheduler_sleep=True)])
        state=dict(revision=8,settings=off['settings'],write=dict(enabled=False,auto=False),
                   last_refresh=dict(status='ok'),bundles=[])
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'server.py';file.write_bytes(b'old')
            manifest=dict(files=[dict(candidate='source/pack_bundles_server.py',target=str(file),
                sha256=hashlib.sha256(b'new').hexdigest(),beforeSha256=hashlib.sha256(b'old').hexdigest())])
            with patch.object(adapter,'bundle_live_snapshot',return_value=(off,state,process)), \
                 patch.object(adapter,'BUNDLE_SOURCE',file):
                proof=adapter.capture_bundle_bootstrap(baseline)
                self.assertNotIn('config',proof);self.assertNotIn('settings',proof)
                manifest['bundleBootstrap']=proof
                base=SimpleNamespace(rooted=lambda root,path:Path(path))
                adapter.bundle_bootstrap_guard(manifest,base,Path('/'))
                for change in ('revision','settings','thread','sleep','refresh','pid'):
                    config=json.loads(json.dumps(off));live=json.loads(json.dumps(state));proc=json.loads(json.dumps(process))
                    if change=='revision':config['revision']+=1
                    elif change=='settings':config['settings']['interval_hours']=2
                    elif change=='thread':proc['threads'].append(dict(tid=102,start_ticks=1010,scheduler_sleep=True))
                    elif change=='sleep':proc['threads'][1]['scheduler_sleep']=False
                    elif change=='refresh':live['last_refresh']['status']='running'
                    else:proc['pid']=999
                    with self.subTest(change=change),patch.object(adapter,'bundle_live_snapshot',return_value=(config,live,proc)),self.assertRaises(ValueError):
                        adapter.bundle_bootstrap_guard(manifest,base,Path('/'))
                # A new label cannot skip the original admission proof.
                modern=dict(state,write_admission_contract='bundle_write_admission_v1')
                changed_process=dict(process,pid=200)
                file.write_bytes(b'new')
                with patch.object(adapter,'bundle_live_snapshot',return_value=(off,modern,changed_process)):
                    with self.assertRaisesRegex(ValueError,'stage'):adapter.bundle_bootstrap_guard(manifest,base,Path('/'))
                    adapter.bundle_bootstrap_guard(manifest,base,Path('/'),locks_held=True,admitted=True,phase='new')
                file.write_bytes(b'old')
                with patch.object(adapter,'bundle_live_snapshot',return_value=(off,state,changed_process)):
                    adapter.bundle_bootstrap_guard(manifest,base,Path('/'),locks_held=True,admitted=True,phase='rollback')

    @unittest.skipUnless(os.name=='posix','requires publisher Linux flock')
    def test_publisher_cannot_replace_until_shared_dispatch_lock_is_released(self):
        import fcntl
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'write-admission.lock'
            script="""
import os,sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,sys.argv[1])
import fc_v3_release_adapter as a
# CI fixture file may belong to the runner; production uid0 is separately
# enforced by the actual helper and original publisher metadata guards.
original=os.fstat
def metadata(fd):
 values=list(original(fd));values[4]=0;return os.stat_result(values)
os.fstat=metadata
base=SimpleNamespace(rooted=lambda root,p:Path(sys.argv[2]),no_target_link=lambda p:None)
try:
 with a.bundle_release_admission(base,Path('/')):print('published')
except ValueError as e:print(str(e))
"""
            def run():
                return subprocess.run([sys.executable,'-c',script,str(DEPLOY),str(path)],
                    check=True,capture_output=True,text=True).stdout.strip()
            self.assertEqual(run(),'bundles_write_lock_bootstrap_required')
            self.assertFalse(path.exists(),'publisher cannot silently bootstrap a legacy process lock')
            fd=os.open(str(path),os.O_RDWR|os.O_CREAT,0o640)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.assertEqual(run(),'bundles_write_in_progress')
            finally:os.close(fd)
            self.assertEqual(run(),'published')

    def test_bundle_readiness_checks_loaded_contract_and_preserves_rollback_readback(self):
        self.assertTrue(hasattr(adapter,'bundle_readiness'))
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'server.py';file.write_bytes(b'new')
            manifest=dict(files=[dict(candidate='source/pack_bundles_server.py',target=str(file),
                sha256=hashlib.sha256(b'new').hexdigest(),beforeSha256=hashlib.sha256(b'old').hexdigest())])
            def response(state):return io.BytesIO(json.dumps(state).encode())
            old=dict(bundles=[],write={})
            with patch.object(adapter.urllib.request,'urlopen',side_effect=lambda *a,**kw:response(old)), \
                 patch.object(adapter.time,'sleep'):
                with self.assertRaisesRegex(ValueError,'bundles_loaded_contract'):adapter.bundle_readiness(manifest)
            new=dict(old,price_scope_contract='fc27_three_platform_v1',write_admission_contract='bundle_write_admission_v1')
            with patch.object(adapter.urllib.request,'urlopen',side_effect=lambda *a,**kw:response(new)):
                adapter.bundle_readiness(manifest)
            file.write_bytes(b'old')
            with patch.object(adapter.urllib.request,'urlopen',side_effect=lambda *a,**kw:response(old)):
                adapter.bundle_readiness(manifest)

    def test_exact_scope_preserves_old_targets_and_only_adds_six_new_runtime_files(self):
        self.assertTrue(hasattr(target_map, 'THREE_PLATFORM_SCOPE'))
        self.assertEqual(target_map.THREE_PLATFORM_SCOPE, 'fc-pricing-three-platform-20261110')
        self.assertEqual(len(adapter.TARGETS), 101)
        self.assertEqual(target_map.TARGET_COUNT, 101)
        self.assertEqual(len(target_map.three_platform_targets(DEPLOY.parent/'source')), 107)
        self.assertEqual(len(adapter.THREE_PLATFORM_TARGETS), 56)
        self.assertEqual(len(target_map.THREE_PLATFORM_NEW), 7)
        self.assertEqual(len(adapter.BIDIRECTIONAL_TARGETS), 25)
        self.assertEqual(len(adapter.REPAIR_TARGETS), 4)
        self.assertEqual(len(adapter.COUPON_DISPLAY_TARGETS), 5)
        self.assertEqual(adapter.THREE_PLATFORM_TARGETS['source/pack_bundles_server.py'],
                         '/opt/fc27-pack-bundles/pack_bundles_server.py')
        self.assertEqual(adapter.THREE_PLATFORM_TARGETS['source/pack_bundles.html'],
                         '/var/www/dashboard/modules/sports/bundles/index.html')
        self.assertNotIn('source/price_writer.py', adapter.THREE_PLATFORM_TARGETS)
        value = self.manifest()
        self.assertEqual(adapter.checked_manifest(value), value)
        for change in ('missing', 'wrong_new', 'extra', 'timer', 'business'):
            invalid = json.loads(json.dumps(value))
            if change == 'missing': invalid['files'].pop()
            elif change == 'wrong_new':
                new = next(r for r in invalid['files'] if r['beforeSha256'] is None)
                old = next(r for r in invalid['files'] if r['beforeSha256'] is not None)
                new['beforeSha256'] = 'a'*64; old['beforeSha256'] = None
            elif change == 'extra': invalid['files'].append(dict(invalid['files'][0]))
            else: invalid['timersChanged' if change=='timer' else 'businessWrites'] = True
            with self.subTest(change=change), self.assertRaises(ValueError): adapter.checked_manifest(invalid)

    def manifest(self):
        return dict(scope=target_map.THREE_PLATFORM_SCOPE, businessWrites=False, timersChanged=False,
                    releaseReady=True, unchangedRequired=[dict(path=target_map.MONITOR_SQLITE_SOURCE,sha256=target_map.MONITOR_SQLITE_SHA)],
                    files=[dict(candidate=n,target=t,sha256=target_map.MONITOR_SQLITE_SHA if n==target_map.MONITOR_SQLITE_CANDIDATE else 'b'*64,
                        beforeSha256=None if n in target_map.THREE_PLATFORM_NEW else 'a'*64,
                        owner='0:0',mode='0o644') for n,t in adapter.THREE_PLATFORM_TARGETS.items()])

    def test_builder_includes_canonical_bundle_sources_only_in_explicit_mode(self):
        self.assertTrue(hasattr(target_map, 'THREE_PLATFORM_REPOSITORY_SOURCES'))
        def blob(checkout, path): return path.read_bytes().replace(b'\r\n', b'\n')
        def git(command, **kwargs): return 'a'*40 if command[1]=='rev-parse' else ''
        library=Path('private-library-fixture')
        library_bytes=b'\x7fELF\x02\x01fixture'
        with tempfile.TemporaryDirectory() as folder, patch.object(build_stage,'git_blob',side_effect=blob), \
             patch.object(build_stage,'monitor_library',return_value=library_bytes), \
             patch.object(build_stage.subprocess,'check_output',side_effect=git):
            checkout=Path(folder)/'checkout'; release=checkout/'releases/fc-coins/fc-pricing-v3-20261026'
            for name in target_map.three_platform_targets(DEPLOY.parent/'source'):
                file=release/'source'/name.removeprefix('hermes-copy/')
                file.parent.mkdir(parents=True,exist_ok=True)
                file.write_bytes(b'#!/bin/sh\n# fixture\n' if file.suffix=='.sh' else b'# fixture\n')
            for name in ('target_map.py','release_navigation_base.py','fc_v3_release_adapter.py','prepare_manifest.py','release_readiness.py'):
                file=release/'deploy'/name; file.parent.mkdir(exist_ok=True); file.write_bytes((DEPLOY/name).read_bytes())
            for candidate, original in target_map.THREE_PLATFORM_REPOSITORY_SOURCES.items():
                file=checkout/original; file.parent.mkdir(parents=True,exist_ok=True); file.write_text(original)
            for native in (False,True):
                output=Path(folder)/('native.tar.gz' if native else 'old.tar.gz')
                result=build_stage.build(checkout,output,three_platform=native,monitor_sqlite_library=library if native else None)
                with tarfile.open(output,'r:gz') as archive:
                    base='fc-pricing-v3-20261026/'
                    provenance=json.load(archive.extractfile(base+'source-manifest.json'))
                    self.assertEqual(result['targets'],112 if native else 101)
                    self.assertEqual(len(provenance['files']),112 if native else 101)
                    if native:
                        self.assertEqual(provenance['repositorySources'],target_map.THREE_PLATFORM_REPOSITORY_SOURCES)
                        self.assertEqual(provenance['externalSources'],[target_map.MONITOR_SQLITE_PROVENANCE])
                        self.assertEqual(archive.extractfile(base+'candidate/'+target_map.MONITOR_SQLITE_CANDIDATE).read(),library_bytes)
                        for candidate, original in target_map.THREE_PLATFORM_REPOSITORY_SOURCES.items():
                            payload=archive.extractfile(base+'candidate/'+candidate).read()
                            self.assertEqual(payload,(checkout/original).read_bytes())
                    else:
                        self.assertNotIn('repositorySources',provenance)
                        self.assertFalse(set(target_map.THREE_PLATFORM_NEW)&set(provenance['files']))

    def test_builder_rejects_dirty_external_bundle_source(self):
        def git(command, **kwargs):
            if command[1]=='rev-parse': return 'a'*40
            self.assertIn('fc27_pack_bundles_20261013/src/pack_bundles_server.py',command)
            self.assertIn('fc27_pack_bundles_20261013/web/index.html',command)
            return ' M fc27_pack_bundles_20261013/web/index.html'
        with tempfile.TemporaryDirectory() as folder,patch.object(build_stage.subprocess,'check_output',side_effect=git):
            with self.assertRaisesRegex(ValueError,'source_tree_has_uncommitted_changes'):
                build_stage.build(ROOT,Path(folder)/'unsafe.tar.gz',three_platform=True)

    def test_monitor_library_requires_exact_existing_elf_and_protected_source(self):
        with self.assertRaisesRegex(ValueError,'monitor_sqlite_library_required'):build_stage.monitor_library(None)
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'library';file.write_bytes(b'not an ELF')
            with self.assertRaisesRegex(ValueError,'monitor_sqlite_library_sha_mismatch'):build_stage.monitor_library(file)
            payload=b'\x7fELF\x02\x01fixture';file.write_bytes(payload)
            with self.assertRaisesRegex(ValueError,'monitor_sqlite_library_sha_mismatch'):build_stage.monitor_library(file)
            with patch.object(build_stage,'MONITOR_SQLITE_SHA',hashlib.sha256(payload).hexdigest()):
                self.assertEqual(build_stage.monitor_library(file),payload)
        value=self.manifest();value['unchangedRequired']=[]
        with self.assertRaisesRegex(ValueError,'monitor_sqlite_provenance_changed'):adapter.checked_manifest(value)
        value=self.manifest();next(r for r in value['files'] if r['candidate']==target_map.MONITOR_SQLITE_CANDIDATE)['sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'monitor_sqlite_provenance_changed'):adapter.checked_manifest(value)

    def test_prepare_requires_exact_new_identities_and_keeps_collection_and_model_protection(self):
        self.assertTrue(hasattr(target_map, 'THREE_PLATFORM_NAMES'))
        with tempfile.TemporaryDirectory() as folder:
            stage=Path(folder); deploy=stage/'deploy'; deploy.mkdir()
            names=list(target_map.THREE_PLATFORM_NAMES)+['source/pricing_state.py']
            mapping={}; extra={}
            for i,name in enumerate(names):
                candidate=stage/'candidate'/name; candidate.parent.mkdir(parents=True,exist_ok=True);candidate.write_text(name)
                live=stage/'live'/str(i);live.parent.mkdir(exist_ok=True)
                if name not in target_map.THREE_PLATFORM_NEW: live.write_text('old:'+name)
                if name in target_map.THREE_PLATFORM_EXTRA: extra[name]=str(live)
                else: mapping[name.removeprefix('source/')]=str(live)
            sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else 'a'*64
            provenance=dict(sourceCommit='a'*40,files={n:sha(stage/'candidate'/n) for n in names},
                            repositorySources=target_map.THREE_PLATFORM_REPOSITORY_SOURCES,externalSources=[target_map.MONITOR_SQLITE_PROVENANCE])
            (stage/'source-manifest.json').write_text(json.dumps(provenance))
            base=SimpleNamespace(HERMES_TARGETS={},HERMES_CAPABILITY_TARGETS={},CAP_PROTECTED_SESSION=set(),HERMES_DIRECT_TARGETS={})
            inspect=Mock(return_value={'ok':True})
            with patch.object(prepare,'STAGE',stage),patch.object(prepare,'HERE',deploy), \
                 patch.object(prepare,'three_platform_targets',return_value=mapping), \
                 patch.object(prepare,'THREE_PLATFORM_TARGET_COUNT',len(mapping)), \
                 patch.object(prepare,'THREE_PLATFORM_EXTRA',extra),patch.object(prepare,'regular'), \
                 patch.object(prepare,'sha',side_effect=sha),patch.object(prepare,'MONITOR_SQLITE_SHA',sha(stage/'candidate'/target_map.MONITOR_SQLITE_CANDIDATE)),patch.object(prepare,'load_base',return_value=base), \
                 patch.object(adapter,'load_base',return_value=SimpleNamespace(inspect=inspect)), \
                 patch.object(prepare.subprocess,'check_output',return_value='ActiveState=active') as system:
                result=prepare.prepare(three_platform=True)
                manifest=json.loads((stage/'approved-manifest.json').read_text())
                self.assertEqual(result['files'],56);self.assertEqual(result['new'],7)
                self.assertEqual({r['candidate'] for r in manifest['files'] if r['beforeSha256'] is None},target_map.THREE_PLATFORM_NEW)
                self.assertIn('fc27-pack-bundles.service',manifest['runtimeRequired'])
                self.assertTrue(set(target_map.COUPON_DISPLAY_PROTECTED).issubset({r['path'] for r in manifest['unchangedRequired']}))
                self.assertIn(mapping['pricing_state.py'],{r['path'] for r in manifest['unchangedRequired']})
                self.assertEqual((stage/'approved-manifest.json').read_bytes(),(deploy/'approved-manifest.json').read_bytes())
                inspect.assert_called_once_with(manifest,stage)

    def test_three_platform_cli_mode_is_explicit_and_exclusive(self):
        for script in ('prepare_manifest.py','build_stage.py'):
            result=subprocess.run([sys.executable,'-B',str(DEPLOY/script),'--help'],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr);self.assertIn('--three-platform',result.stdout)
        for script in ('prepare_manifest.py','build_stage.py'):
            command=[sys.executable,'-B',str(DEPLOY/script),'--three-platform','--coupon-display']
            if script=='build_stage.py': command += [str(ROOT),'unused.tar.gz']
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)


if __name__=='__main__': unittest.main()
