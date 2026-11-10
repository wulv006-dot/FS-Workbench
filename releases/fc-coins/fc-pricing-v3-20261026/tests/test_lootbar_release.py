"""Exact source-only rollout: legacy scopes, role hashes and renderer rollback."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import tarfile
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock
from contextlib import ExitStack
from datetime import datetime,timedelta,timezone

DEPLOY=Path(__file__).resolve().parents[1]/'deploy'
sys.path.insert(0,str(DEPLOY))
import target_map
import fc_v3_release_adapter as adapter
import update_collection_bidirectional as updater
import build_collection_node as builder
import build_stage
import prepare_manifest as prepare


class LootbarRelease(unittest.TestCase):
    def test_renderer_process_query_keeps_pid_and_counts_only_actual_workers(self):
        container=dict(Id='original-container',Image=updater.LOOTBAR_RENDERER_IMAGE,
            State=dict(Running=True,Pid=100,StartedAt='original-start'),
            Mounts=[dict(Source='/opt/d4follow',Destination='/app',RW=False)],
            HostConfig=dict(updater.LOOTBAR_RENDERER_RESOURCES,
                PortBindings={'9223/tcp':[{'HostIp':'127.0.0.1','HostPort':'9223'}]}))
        for count in (0,2):
            with self.subTest(workers=count):
                rows=['PID COMMAND','100 /usr/bin/python3 /app/_qd_render/qd_render_svc.py',
                      '101 chromium --worker-process']
                rows += [str(200+i)+' /usr/bin/python3 /app/_qd_render/qd_render_svc.py --worker' for i in range(count)]
                def command(args,**kwargs):
                    if args[:2]==['docker','inspect']:return json.dumps(container)
                    if args[:2]==['docker','top']:
                        if args[-1]!='pid,args':
                            raise subprocess.CalledProcessError(1,args,output="Couldn't find PID field in ps output")
                        return '\n'.join(rows)+'\n'
                    if args[0]=='ss':return ''
                    if args[:2]==['systemctl','show']:return 'original timer state\n'
                    if args[:2]==['systemctl','list-timers']:return 'Wed 2026-11-11 02:00:00 CST original timer\n'
                    raise AssertionError('unexpected command: '+str(args))
                body=json.dumps(dict(data=dict(tasks=[dict(id='original',status='done')])))
                with patch.object(updater.subprocess,'check_output',side_effect=command) as calls, \
                        patch.object(updater.urllib.request,'urlopen',side_effect=lambda *a,**k:io.StringIO(body)):
                    state=updater._lootbar_renderer_state()
                top=next(c for c in calls.call_args_list if c.args[0][:2]==['docker','top'])
                self.assertEqual(top.args[0],['docker','top','qd-render','-eo','pid,args'])
                self.assertEqual(state['workers'],count)
                self.assertEqual(state['pid'],100)
                if count:
                    with self.assertRaisesRegex(ValueError,'renderer_worker_active'):
                        updater.lootbar_renderer_window(state,'original')
                else:updater.lootbar_renderer_window(state,'original')

    def role_fixture(self,folder,stack,role):
        root=Path(folder)/role;(root/'code/fc_collection').mkdir(parents=True);stage=Path(folder)/'stage';stage.mkdir()
        bundle=stage/(role+'.zip');builder.build(bundle,role)
        with zipfile.ZipFile(bundle) as z:new_digest=hashlib.sha256(z.read('manifest.json')).hexdigest()
        old_files={n:('# old '+n).encode() for n in updater.LOOTBAR_ROLE_FILES[role]-{'fc_collection/lootbar.py','manifest.json'}}
        old_manifest=dict(schema_version=1,role='limited_fc_collector' if role=='node' else 'fc_collection_controller',sources=['ArabUT'],credentials=[],business_runtime=False,production_consume=False,sha256={n:hashlib.sha256(b).hexdigest() for n,b in old_files.items()})
        old_files['manifest.json']=json.dumps(old_manifest).encode()
        for n,b in old_files.items():(root/'code'/n).write_bytes(b)
        protected=root/'protected';protected.write_bytes(b'original routing/unit')
        spool=root/'spool';spool.mkdir();access=root/'access.json';access.write_text(json.dumps(dict(worker_digest=updater.WORKER,host='unchanged',identity_file='private-placeholder')));access.chmod(0o600)
        stack.enter_context(patch.dict(updater.LOOTBAR_ROOTS,{role:root}))
        stack.enter_context(patch.dict(updater.LOOTBAR_BEFORE_MANIFEST,{role:hashlib.sha256(old_files['manifest.json']).hexdigest()}))
        stack.enter_context(patch.dict(updater.LOOTBAR_ROLE_PROTECTED,{role:(str(protected),)}))
        stack.enter_context(patch.object(updater,'LOOTBAR_SPOOL',spool));stack.enter_context(patch.object(updater,'LOOTBAR_ACCESS',access))
        stack.enter_context(patch.object(updater,'_lootbar_root_owned',return_value=True))
        stack.enter_context(patch.object(updater.os,'geteuid',return_value=0,create=True))
        stack.enter_context(patch.object(updater.socket,'gethostname',return_value='play187' if role=='control' else 'FSHTUS01'))
        m=updater.prepare_lootbar(role,bundle,hashlib.sha256(bundle.read_bytes()).hexdigest(),'original-release','a'*40,worker_digest=new_digest)
        path=stage/'manifest.json';path.write_text(json.dumps(m));digest=hashlib.sha256(path.read_bytes()).hexdigest()
        return root,path,digest,old_files,access

    def renderer_fixture(self,folder,stack,installed=False,baseline_name='LOOTBAR_RENDERER_INSTALLED'):
        root=Path(folder)/'renderer';root.mkdir();stage=Path(folder)/'stage';stage.mkdir()
        (root/'qd_render_svc.py').write_bytes(b'original renderer')
        protected=root/'protected';protected.write_bytes(b'protected source/config')
        files={'qd_render_svc.py':b'new renderer','fc27_lootbar.py':b'fixed FC task','lootbar_background.js':b'fixed parser'}
        bundle=stage/'renderer.zip'
        with zipfile.ZipFile(bundle,'w') as z:
            for n,b in files.items():z.writestr(n,b)
        state=dict(container_id='original-container',image_id=updater.LOOTBAR_RENDERER_IMAGE,pid=10,started_at='old',timer='original timer',
            next_at=(datetime.now(timezone.utc)+timedelta(minutes=4)).isoformat(),workers=0,active_requests=0,
            tasks=[dict(id='original-task',kind='collect',status='running')],resources={'original':True})
        stack.enter_context(patch.dict(updater.LOOTBAR_ROOTS,renderer=root))
        stack.enter_context(patch.object(updater,'LOOTBAR_RENDERER_PROTECTED',(str(protected),)))
        stack.enter_context(patch.object(updater,'LOOTBAR_RENDERER_BEFORE',hashlib.sha256(b'original renderer').hexdigest()))
        if installed:
            original={'qd_render_svc.py':b'installed renderer','fc27_lootbar.py':b'previous FC task','lootbar_background.js':b'previous parser'}
            for n,b in original.items():(root/n).write_bytes(b)
            stack.enter_context(patch.object(updater,baseline_name,{n:hashlib.sha256(b).hexdigest() for n,b in original.items()},create=True))
        stack.enter_context(patch.object(updater,'LOOTBAR_PARSER_SHA',hashlib.sha256(b'fixed parser').hexdigest()))
        stack.enter_context(patch.object(updater,'_lootbar_renderer_state',side_effect=lambda:dict(state)))
        stack.enter_context(patch.object(updater.os,'geteuid',return_value=0,create=True))
        stack.enter_context(patch.object(updater.socket,'gethostname',return_value='FSHTUS01'))
        m=updater.prepare_lootbar('renderer',bundle,hashlib.sha256(bundle.read_bytes()).hexdigest(),'original-release','a'*40,original_task='original-task')
        path=stage/'manifest.json';path.write_text(json.dumps(m));digest=hashlib.sha256(path.read_bytes()).hexdigest()
        return root,path,digest,state,files

    def test_caller_scope_exact_six_without_changing_legacy_counts(self):
        self.assertEqual(target_map.TARGET_COUNT,101)
        self.assertEqual(len(target_map.THREE_PLATFORM_NAMES),56)
        self.assertEqual(set(target_map.LOOTBAR_CALLER_NAMES),{'source/snapshot_layer.py','source/server_quote_job.py',
            'source/fc27_cloud_worker.py','source/collect_lootbar.sh','source/lootbar-collector/lootbar_server_collector.py','source/lootbar-collector/background.js'})
        self.assertEqual(set(adapter.LOOTBAR_CALLER_TARGETS),set(target_map.LOOTBAR_CALLER_NAMES))
        self.assertEqual(len(adapter.BIDIRECTIONAL_TARGETS),25)
        self.assertEqual(updater.OLD['node'],'55eeff178d37e4747c1fe5b4f3d49b9a258b4d5cf7eeb75a6cbf6493cba5b14d')
        value=dict(scope=target_map.LOOTBAR_CALLER_SCOPE,businessWrites=False,timersChanged=False,releaseReady=True,
            files=[dict(candidate=n,target=t,owner='0:0',mode='0o755' if n.endswith('.sh') else '0o644',beforeSha256='a'*64,sha256='b'*64) for n,t in adapter.LOOTBAR_CALLER_TARGETS.items()])
        adapter.checked_manifest(value)
        value['files'][-1]['beforeSha256']=None
        with self.assertRaisesRegex(ValueError,'new_existing'):adapter.checked_manifest(value)

    def test_explicit_stage_and_prepare_use_exact_six_and_protect_other_98(self):
        checkout=DEPLOY.parents[3]
        def git(command,**kwargs):return 'a'*40 if 'rev-parse' in command else ''
        with tempfile.TemporaryDirectory() as folder,patch.object(build_stage.subprocess,'check_output',side_effect=git),patch.object(build_stage,'git_blob',side_effect=lambda c,p:Path(p).read_bytes().replace(b'\r\n',b'\n')):
            archive=Path(folder)/'stage.tgz';built=build_stage.build(checkout,archive,lootbar=True)
            self.assertEqual(built['targets'],104)
            with tarfile.open(archive) as tar:tar.extractall(Path(folder)/'unpacked')
            stage=Path(folder)/'unpacked/fc-pricing-v3-20261026';provenance=json.loads((stage/'source-manifest.json').read_text())
            self.assertEqual(provenance['repositorySources'],target_map.LOOTBAR_CALLER_REPOSITORY_SOURCES)
            mapping={};extra={}
            for i,n in enumerate(provenance['files']):
                p=Path(folder)/'live'/str(i);p.parent.mkdir(exist_ok=True);p.write_bytes(b'original');p.chmod(0o755 if n.endswith('.sh') else 0o644)
                if n in target_map.LOOTBAR_CALLER_EXTRA:extra[n]=str(p)
                else:mapping[n.removeprefix('source/')]=str(p)
            original=SimpleNamespace(HERMES_TARGETS={},HERMES_CAPABILITY_TARGETS={},CAP_PROTECTED_SESSION=set(),HERMES_DIRECT_TARGETS={})
            digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).is_file() else 'a'*64
            with patch.object(prepare,'STAGE',stage),patch.object(prepare,'HERE',stage/'deploy'),patch.object(prepare,'targets',return_value=mapping),patch.object(prepare,'LOOTBAR_CALLER_EXTRA',extra),patch.object(prepare,'load_base',return_value=original),patch.object(prepare,'regular'),patch.object(prepare,'sha',side_effect=digest),patch.object(prepare.subprocess,'check_output',return_value='ActiveState=active'),patch.object(adapter,'load_base',return_value=SimpleNamespace(inspect=Mock(return_value={'ok':True}))):
                result=prepare.prepare(lootbar=True)
            self.assertEqual(result['files'],6);self.assertEqual(result['new'],0)
            manifest=json.loads((stage/'approved-manifest.json').read_text())
            self.assertEqual(manifest['scope'],target_map.LOOTBAR_CALLER_SCOPE)
            self.assertEqual({x['candidate'] for x in manifest['files']},set(target_map.LOOTBAR_CALLER_NAMES))
            self.assertEqual((stage/'approved-manifest.json').read_bytes(),(stage/'deploy/approved-manifest.json').read_bytes())
            self.assertGreaterEqual(len(manifest['unchangedRequired']),98)

    def test_role_bundle_exact_lists_and_manifest_not_a_renderer_package(self):
        with tempfile.TemporaryDirectory() as folder:
            for role in ('node','control'):
                p=Path(folder)/(role+'.zip');builder.build(p,role)
                files=updater.read_lootbar_bundle(p,hashlib.sha256(p.read_bytes()).hexdigest(),role)
                self.assertEqual(set(files),updater.LOOTBAR_ROLE_FILES[role])
                self.assertIn('fc_collection/lootbar.py',files)
                self.assertNotIn('fc_collection/lootbar_browser.py',files)
            with self.assertRaisesRegex(ValueError,'files'):
                updater.read_lootbar_bundle(p,hashlib.sha256(p.read_bytes()).hexdigest(),'renderer')
            with zipfile.ZipFile(p,'a') as z:z.writestr('extra.py',b'bad')
            with self.assertRaisesRegex(ValueError,'files'):
                updater.read_lootbar_bundle(p,hashlib.sha256(p.read_bytes()).hexdigest(),'control')

    def test_access_digest_cas_changes_only_that_field(self):
        original=json.dumps({'host':'example','identity_file':'private-placeholder','worker_digest':'a'*64}).encode()
        result=updater.lootbar_access_bytes(original,hashlib.sha256(original).hexdigest(),'a'*64,'b'*64)
        self.assertEqual(json.loads(result),dict(json.loads(original),worker_digest='b'*64))
        with self.assertRaisesRegex(ValueError,'access.*drift'):
            updater.lootbar_access_bytes(original,'c'*64,'a'*64,'b'*64)
        with self.assertRaisesRegex(ValueError,'digest'):
            updater.lootbar_access_bytes(original,hashlib.sha256(original).hexdigest(),'c'*64,'b'*64)

    def test_renderer_checks_actual_browser_not_whole_RPG_task_duration(self):
        state=dict(container_id='x',image_id='y',timer='unchanged',tasks=[dict(id='original',status='running')],workers=0)
        updater.lootbar_renderer_window(state,'original')
        with self.assertRaisesRegex(ValueError,'original_task_unverified'):
            updater.lootbar_renderer_window(state,'missing')
        state['tasks'][0]['status']='done';updater.lootbar_renderer_window(state,'original')
        state['workers']=1
        with self.assertRaisesRegex(ValueError,'renderer_worker_active'):
            updater.lootbar_renderer_window(state,'original')
        state['workers']=0;state['active_requests']=1
        with self.assertRaisesRegex(ValueError,'renderer_request_active'):
            updater.lootbar_renderer_window(state,'original')

    def test_renderer_preview_then_same_container_reload_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            root,path,digest,state,files=self.renderer_fixture(folder,stack)
            def restart():state.update(pid=11,started_at='new')
            restart_mock=stack.enter_context(patch.object(updater,'_lootbar_restart_renderer',side_effect=restart))
            process=stack.enter_context(patch.object(updater.subprocess,'run'))
            self.assertEqual(updater.update_lootbar(path,False,digest)['phase'],'preview')
            self.assertEqual((root/'qd_render_svc.py').read_bytes(),b'original renderer')
            self.assertFalse((root/'fc27_lootbar.py').exists());restart_mock.assert_not_called()
            self.assertEqual(updater.update_lootbar(path,True,digest)['phase'],'updated')
            self.assertEqual(updater.update_lootbar(path,True,digest)['phase'],'already_updated')
            for n,b in files.items():self.assertEqual((root/n).read_bytes(),b)
            restart_mock.assert_called_once();process.assert_not_called()

    def test_renderer_failed_reload_restores_original_and_records_same_release(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            root,path,digest,state,files=self.renderer_fixture(folder,stack)
            reload=stack.enter_context(patch.object(updater,'_lootbar_restart_renderer',side_effect=[ValueError('failed health'),None]))
            with self.assertRaisesRegex(ValueError,'failed health'):updater.update_lootbar(path,True,digest)
            self.assertEqual((root/'qd_render_svc.py').read_bytes(),b'original renderer')
            self.assertFalse((root/'fc27_lootbar.py').exists());self.assertFalse((root/'lootbar_background.js').exists())
            self.assertEqual(reload.call_count,2)
            receipt=json.loads((root/'lootbar-original-release.json').read_text());self.assertEqual(receipt['phase'],'rolled_back')
            with self.assertRaisesRegex(ValueError,'receipt_requires_reconciliation'):updater.update_lootbar(path,True,digest)

    def test_renderer_known_installed_baseline_exact_update_preserves_prior_receipt(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            root,path,digest,state,files=self.renderer_fixture(folder,stack,installed=True)
            original={n:(root/n).read_bytes() for n in files}
            prior=root/'lootbar-prior-initial.json';prior.write_bytes(b'{"phase":"updated","release_id":"prior-initial"}\n')
            before_receipt=prior.read_bytes()
            def restart():state.update(pid=11,started_at='new')
            reload=stack.enter_context(patch.object(updater,'_lootbar_restart_renderer',side_effect=restart))
            self.assertEqual(updater.update_lootbar(path,False,digest)['phase'],'preview')
            self.assertEqual({n:(root/n).read_bytes() for n in files},original)
            self.assertEqual(updater.update_lootbar(path,True,digest)['phase'],'updated')
            self.assertEqual(updater.update_lootbar(path,True,digest)['phase'],'already_updated')
            for n,b in files.items():
                self.assertEqual((root/n).read_bytes(),b)
                self.assertEqual((root/'before-lootbar-original-release'/n).read_bytes(),original[n])
            self.assertEqual(prior.read_bytes(),before_receipt);reload.assert_called_once()

    def test_renderer_known_installed_failed_reload_restores_all_three(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            root,path,digest,state,files=self.renderer_fixture(folder,stack,installed=True)
            original={n:(root/n).read_bytes() for n in files}
            prior=root/'lootbar-prior-initial.json';prior.write_bytes(b'{"phase":"updated"}\n')
            reload=stack.enter_context(patch.object(updater,'_lootbar_restart_renderer',side_effect=[ValueError('failed health'),None]))
            with self.assertRaisesRegex(ValueError,'failed health'):updater.update_lootbar(path,True,digest)
            self.assertEqual({n:(root/n).read_bytes() for n in files},original)
            self.assertEqual(prior.read_bytes(),b'{"phase":"updated"}\n')
            self.assertEqual(json.loads((root/'lootbar-original-release.json').read_text())['phase'],'rolled_back')
            self.assertEqual(reload.call_count,2)
            with self.assertRaisesRegex(ValueError,'receipt_requires_reconciliation'):updater.update_lootbar(path,True,digest)

    def test_renderer_known_installed_tuple_rejects_mixed_missing_and_manifest_drift(self):
        for name in sorted(updater.LOOTBAR_RENDERER_FILES):
            with self.subTest(target=name),tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
                root,path,digest,state,files=self.renderer_fixture(folder,stack,installed=True)
                original=(root/name).read_bytes();(root/name).write_bytes(b'unapproved bytes')
                bundle=path.parent/'renderer.zip';bundle_sha=hashlib.sha256(bundle.read_bytes()).hexdigest()
                with self.assertRaisesRegex(ValueError,'original_renderer_source_drift'):
                    updater.prepare_lootbar('renderer',bundle,bundle_sha,'another-release','a'*40,original_task='original-task')
                with self.assertRaisesRegex(ValueError,'target_cas_drift'):
                    updater.update_lootbar(path,True,digest)
                (root/name).write_bytes(original)
                m=json.loads(path.read_text());m['before'][name]='a'*64;path.write_text(json.dumps(m))
                with self.assertRaisesRegex(ValueError,'original_renderer_source_drift'):
                    updater.update_lootbar(path,True,hashlib.sha256(path.read_bytes()).hexdigest())
                (root/name).unlink()
                with self.assertRaisesRegex(ValueError,'original_renderer_source_drift'):
                    updater.prepare_lootbar('renderer',bundle,bundle_sha,'another-release','a'*40,original_task='original-task')
                self.assertFalse((root/'before-lootbar-original-release').exists())
                self.assertFalse((root/'lootbar-original-release.json').exists())

    def test_renderer_installed_baseline_pins_complete_actual_three_file_tuple(self):
        self.assertEqual(updater.LOOTBAR_RENDERER_INSTALLED,{
            'qd_render_svc.py':'52854d3f1eb65c4f9090be02289c510a340288a1d80db01cb2f202963718468f',
            'fc27_lootbar.py':'61a29808656f82a2ba0f2b3ea162a74ed62f80d9693d55305e4e51a6d1e34fc2',
            'lootbar_background.js':'e0e1946f607ae37df8547788d3252d05e02f5251ffae9c744ed9e941712e298e'})

    def test_renderer_actual_asset_budget_tuple_accepts_only_complete_known_hashes(self):
        current=dict(updater.LOOTBAR_RENDERER_INSTALLED,**{'fc27_lootbar.py':'f10a10277cc11b8a816ff33727a8fc62612d2881776e18198aaf2012b9d56ccd'})
        updater._lootbar_renderer_before(current)
        for name in current:
            with self.subTest(target=name):
                changed=dict(current);changed[name]='0'*64
                with self.assertRaisesRegex(ValueError,'original_renderer_source_drift'):updater._lootbar_renderer_before(changed)
                changed[name]=None
                with self.assertRaisesRegex(ValueError,'original_renderer_source_drift'):updater._lootbar_renderer_before(changed)

    def test_renderer_asset_budget_baseline_preview_and_failed_update_restore_all_three(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            root,path,digest,state,files=self.renderer_fixture(folder,stack,installed=True,baseline_name='LOOTBAR_RENDERER_ASSET_BUDGET')
            original={n:(root/n).read_bytes() for n in files}
            prior=root/'lootbar-prior-budget.json';prior.write_bytes(b'{"phase":"updated"}\n')
            reload=stack.enter_context(patch.object(updater,'_lootbar_restart_renderer',side_effect=[ValueError('failed health'),None]))
            self.assertEqual(updater.update_lootbar(path,False,digest)['phase'],'preview')
            with self.assertRaisesRegex(ValueError,'failed health'):updater.update_lootbar(path,True,digest)
            self.assertEqual({n:(root/n).read_bytes() for n in files},original)
            self.assertEqual(prior.read_bytes(),b'{"phase":"updated"}\n');self.assertEqual(reload.call_count,2)
            self.assertEqual(json.loads((root/'lootbar-original-release.json').read_text())['phase'],'rolled_back')

    def test_manifest_hash_target_drift_and_missing_protection_reject_before_writes(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            root,path,digest,state,files=self.renderer_fixture(folder,stack)
            with self.assertRaisesRegex(ValueError,'manifest_sha256'):updater.update_lootbar(path,True,'b'*64)
            m=json.loads(path.read_text());m['protected']={};path.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError,'exact_protection'):updater.update_lootbar(path,True,hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual((root/'qd_render_svc.py').read_bytes(),b'original renderer')

    def test_role_atomic_swap_updates_only_control_digest_and_node_service(self):
        for role in ('node','control'):
            with self.subTest(role=role),tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
                root,path,digest,old_files,access=self.role_fixture(folder,stack,role)
                before_access=json.loads(access.read_text());health=stack.enter_context(patch.object(updater,'_lootbar_role_health'))
                process=stack.enter_context(patch.object(updater.subprocess,'run'))
                self.assertEqual(updater.update_lootbar(path,False,digest)['phase'],'preview')
                old_umask=os.umask(0o077)
                try:self.assertEqual(updater.update_lootbar(path,True,digest)['phase'],'updated')
                finally:os.umask(old_umask)
                self.assertTrue((root/'code/fc_collection/lootbar.py').is_file())
                if os.name=='posix':self.assertEqual((root/'code/fc_collection').stat().st_mode&0o777,0o755)
                self.assertEqual((root/'before-lootbar-original-release/manifest.json').read_bytes(),old_files['manifest.json'])
                if role=='control':
                    after=json.loads(access.read_text());self.assertNotEqual(after['worker_digest'],before_access['worker_digest'])
                    self.assertEqual({k:v for k,v in after.items() if k!='worker_digest'},{k:v for k,v in before_access.items() if k!='worker_digest'})
                    process.assert_not_called();health.assert_not_called()
                else:
                    self.assertEqual(json.loads(access.read_text()),before_access)
                    health.assert_called_once();self.assertEqual(process.call_count,2)
                self.assertEqual(updater.update_lootbar(path,True,digest)['phase'],'already_updated')

    def test_node_failed_health_restores_whole_original_role(self):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            root,path,digest,old_files,access=self.role_fixture(folder,stack,'node')
            health=stack.enter_context(patch.object(updater,'_lootbar_role_health',side_effect=[ValueError('new node unhealthy'),None]))
            stack.enter_context(patch.object(updater.subprocess,'run'))
            with self.assertRaisesRegex(ValueError,'new node unhealthy'):updater.update_lootbar(path,True,digest)
            self.assertEqual({p.relative_to(root/'code').as_posix():p.read_bytes() for p in (root/'code').rglob('*') if p.is_file()},old_files)
            self.assertEqual(health.call_count,2)
            self.assertEqual(json.loads((root/'lootbar-original-release.json').read_text())['phase'],'rolled_back')


if __name__=='__main__':unittest.main()
