"""Exercise actual inherited source CAS/rollback plus the restricted image leaf."""
from copy import deepcopy
import hashlib,json,contextlib,io
from pathlib import Path
import sys,tempfile,types,unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[4]
RELEASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(RELEASE/'publisher'))
import release_navigation as bridge
import es_image_lifecycle as leaf
import marketing_maintenance as maintenance
import subprocess
import prepare_release


def sha(raw):return hashlib.sha256(raw).hexdigest()


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.stage=self.folder/'stage';self.root=self.folder/'root';self.root.mkdir();self.base=bridge.load_base()
        maps=[]
        for candidate,target in bridge.TARGETS.items():
            before=None if candidate in bridge.NEW_ALLOWED else sha(b'old-code')
            if candidate.endswith('fc27-p2pah-session.service'):
                raw=(RELEASE/'source/fc27-p2pah-session.service').read_bytes();self.old_unit=raw.replace(leaf.NEW_TAG.encode(),leaf.OLD_TAG.encode()).replace(b' --mount type=bind,src=/var/lib/fc27-es-exports,dst=/var/lib/fc27-es-exports',b'');before=sha(self.old_unit)
            maps.append({'runtime':target,'observed_before_sha256':before,'existed':before is not None})
        properties={'Id':'fs-marketing-range.service','MainPID':'123','KillMode':'control-group','ControlGroup':'/system.slice/fs-marketing-range.service','FragmentPath':'/etc/systemd/system/fs-marketing-range.service','DropInPaths':'','ActiveState':'active','SubState':'running','UnitFileState':'enabled'}
        self.admission={'files':[{'path':bridge.ABSENT,'exists':False}], 'units':{'fs-marketing-range.service':'\n'.join(k+'='+v for k,v in properties.items())}}
        for unit in bridge.TIMERS:self.admission['units'][unit]='\n'.join(('ActiveState=active','SubState=waiting','UnitFileState=enabled','PROBE_EXIT=0'))
        prepare_release.prepare(ROOT,self.stage,{'rows':maps},{'files':[{'path':p,'exists':True,'sha256':sha(b'protected')} for p in prepare_release.required_paths(self.base)],'session_image_id':leaf.BASE_IMAGE},'a'*40,self.admission)
        self.manifest=json.loads((self.stage/'approved-manifest.json').read_text('utf-8'));self.manifest['baselinePending']=[]
        for row in self.manifest['unchangedRequired']:
            path=self.root/row['path'].lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'protected')
        for row in self.manifest['files']:
            if row['beforeSha256'] is not None:
                path=self.root/row['target'].lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(self.old_unit if row['candidate'].endswith('fc27-p2pah-session.service') else b'old-code')

    def test_frozen_base_and_exact_closed_payload(self):
        self.assertEqual(sha((RELEASE/'publisher/release_navigation_base.py').read_bytes()),bridge.BASE_SHA)
        self.assertEqual(len(self.base.validate(self.manifest,self.stage)),20)
        self.assertFalse(self.manifest['releaseReady'])
        ordered=sorted(self.manifest['files'],key=self.base.traffic_install_key)
        self.assertTrue(all(r['candidate'].endswith('/traffic_contract.py') for r in ordered[:3]))
        self.assertLess(next(i for i,r in enumerate(ordered) if r['candidate']=='contract/details/traffic_contract.py'),next(i for i,r in enumerate(ordered) if r['candidate']=='contract/details/collect_details.py'))
        self.assertFalse(any('source_snapshots' in r['candidate'] or r['target'].endswith('.timer') for r in self.manifest['files']))
        self.assertIn('test_prepare_ui',(ROOT/'tools/pr_fast.py').read_text('utf-8'))

    def test_actual_inspect_cas_and_drift(self):
        with patch.object(self.base,'guards'),patch.object(self.base,'retirement'),patch.object(bridge,'reviewed_leaf',return_value=types.SimpleNamespace(baseline=lambda *a:None,NEW_TAG=leaf.NEW_TAG,OLD_TAG=leaf.OLD_TAG)),patch.object(bridge,'reviewed_marketing',return_value=types.SimpleNamespace(identity=lambda *a,**k:None)):
            result=self.base.inspect(self.manifest,self.stage,self.root)
            self.assertEqual(result['sourceCAS'],'passed');self.assertFalse(result['mutations'])
            row=next(r for r in self.manifest['files'] if r['beforeSha256'] is not None)
            (self.root/row['target'].lstrip('/')).write_bytes(b'unrelated-newer-code')
            with self.assertRaisesRegex(ValueError,'baseline drift'):self.base.inspect(self.manifest,self.stage,self.root)

    def test_new_file_whitelist_and_paired_source_reject(self):
        changed=deepcopy(self.manifest);next(r for r in changed['files'] if r['candidate']=='hermes/controller.py')['beforeSha256']=None
        with self.assertRaisesRegex(ValueError,'baselines required|whitelist'):self.base.validate(changed,self.stage)
        changed=deepcopy(self.manifest);changed['files'].pop()
        with self.assertRaisesRegex(ValueError,'exact approved scope'):self.base.validate(changed,self.stage)
        changed=deepcopy(self.manifest);changed['baselinePending']=['unknown-current-source']
        with self.assertRaisesRegex(ValueError,'baselines_pending'):self.base.validate(changed,self.stage)

    def test_actual_rollback_keeps_data_and_preserves_drift(self):
        row=next(r for r in self.manifest['files'] if r['candidate']=='hermes/es_order_structure.py')
        target=self.root/row['target'].lstrip('/');target.parent.mkdir(parents=True,exist_ok=True);payload=(self.stage/'candidate'/row['candidate']).read_bytes();target.write_bytes(payload)
        backup=self.folder/'backup';backup.mkdir();data=self.root/'var/lib/fc27-es-exports/evidence.xlsx';data.parent.mkdir(parents=True);data.write_bytes(b'private-evidence')
        attempt=self.root/'var/lib/fs-hermes-fc/fs/es-structures/original.attempt';attempt.parent.mkdir(parents=True);attempt.write_bytes(b'unknown-original-attempt')
        journal={'manifest':self.manifest,'approvedManifestSha256':'a'*64,'files':[{**row,'beforeMode':0o644,'written':True,'intent':True}]}
        with patch.object(self.base,'rollback_credentials'),patch.object(self.base,'traffic_restore'),patch.object(self.base,'directory_sync'),patch.object(bridge,'reviewed_marketing',return_value=types.SimpleNamespace(ensure_stopped=lambda *a,**k:a[2].update(marketingStopped=True))):
            self.base.rollback_journal(backup,journal,self.root)
        self.assertFalse(target.exists());self.assertEqual(data.read_bytes(),b'private-evidence');self.assertEqual(attempt.read_bytes(),b'unknown-original-attempt')
        self.assertTrue((backup/'removed-new-files'/row['candidate']).exists())
        target.write_bytes(b'newer-other-change');journal['files'][0].update(written=True,rollbackIntent=False)
        with patch.object(self.base,'rollback_credentials'),patch.object(self.base,'traffic_restore'),patch.object(self.base,'directory_sync'),patch.object(bridge,'reviewed_marketing',return_value=types.SimpleNamespace(ensure_stopped=lambda *a,**k:a[2].update(marketingStopped=True))):
            with self.assertRaisesRegex(ValueError,'drift'):self.base.rollback_journal(backup,journal,self.root)
        self.assertEqual(target.read_bytes(),b'newer-other-change')

    def test_image_unknown_never_rebuilds_and_old_tag_unchanged(self):
        journal={'sessionBuildIntent':True};calls=[]
        with patch.object(leaf.subprocess,'run',side_effect=lambda *a,**k:calls.append(a)):
            with self.assertRaisesRegex(ValueError,'requires_reconcile'):leaf.apply(self.manifest,self.folder,journal,self.root,None,None,None,None)
        self.assertEqual(calls,[])
        with patch.object(leaf,'running',return_value={'Image':leaf.BASE_IMAGE}),patch.object(leaf,'image_id',return_value=leaf.BASE_IMAGE),patch.object(leaf,'restart_health') as restart,patch.object(leaf.subprocess,'run') as run:
            leaf.restore(self.folder,{'sessionBuildIntent':True},self.root,lambda *a:None)
        restart.assert_called_once_with(leaf.BASE_IMAGE);run.assert_not_called()

    def test_image_build_is_offline_exact_and_journaled_before_command(self):
        backup=self.folder/'image-backup';backup.mkdir();expected={}
        for row in self.manifest['files']:
            if row['candidate'].startswith('session/') and not row['candidate'].endswith('.service'):
                path=self.root/row['target'].lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((self.stage/'candidate'/row['candidate']).read_bytes())
                if path.name in leaf.NAMES:expected['/usr/local/bin/'+path.name]=row['sha256']
        journal={};commands=[];built='sha256:'+'b'*64
        def command(args,**kwargs):
            self.assertTrue(journal['sessionBuildIntent']);commands.append(args)
            return types.SimpleNamespace(returncode=0)
        output=''.join(v+'  '+k+'\n' for k,v in expected.items())
        with patch.object(leaf,'baseline'),patch.object(leaf,'archive_boundary'),patch.object(leaf,'image_id',side_effect=lambda tag:leaf.BASE_IMAGE if tag==leaf.OLD_TAG else built),patch.object(leaf,'running',return_value={'Image':leaf.BASE_IMAGE}),patch.object(leaf,'restart_health') as health,patch.object(leaf.subprocess,'run',side_effect=command),patch.object(leaf.subprocess,'check_output',return_value=output),patch.object(self.base,'directory_sync'):
            leaf.apply(self.manifest,backup,journal,self.root,self.base.atomic,lambda *a:None,self.base.digest,self.base.no_target_link)
        health.assert_called_once_with(built,True)
        self.assertTrue(journal['sessionImageWritten']);self.assertEqual(len(commands),1)
        self.assertIn('--pull=false',commands[0]);self.assertIn('SESSION_BASE_IMAGE='+leaf.BASE_IMAGE,commands[0])
        self.assertEqual(commands[0][commands[0].index('--network')+1],'none');self.assertNotIn('tag',commands[0])

    def test_session_unit_cannot_expand_privileges_and_shared_rule_cannot_split(self):
        changed=deepcopy(self.manifest);row=next(r for r in changed['files'] if r['candidate']=='session/fc27-p2pah-session.service');path=self.stage/'candidate'/row['candidate'];original=path.read_bytes();path.write_bytes(original.replace(b' --read-only ',b' --privileged --read-only '));row['sha256']=sha(path.read_bytes())
        with self.assertRaisesRegex(ValueError,'unit_expanded_scope'):self.base.validate(changed,self.stage)
        path.write_bytes(original)
        changed=deepcopy(self.manifest);row=next(r for r in changed['files'] if r['candidate']=='session/traffic_contract.py');path=self.stage/'candidate'/row['candidate'];path.write_bytes(path.read_bytes()+b'\n# changed');row['sha256']=sha(path.read_bytes())
        with self.assertRaisesRegex(ValueError,'paired_shared_source'):self.base.validate(changed,self.stage)

    def test_container_absence_is_distinct_from_unknown_daemon_failure(self):
        with patch.object(leaf.subprocess,'run',return_value=types.SimpleNamespace(returncode=1,stderr='No such object: fc27-p2pah-session',stdout='')):
            self.assertIsNone(leaf.running(missing=True))
            with self.assertRaisesRegex(ValueError,'inspection_failed'):leaf.running()
        with patch.object(leaf.subprocess,'run',return_value=types.SimpleNamespace(returncode=1,stderr='daemon unavailable',stdout='')):
            with self.assertRaisesRegex(ValueError,'inspection_failed'):leaf.running(missing=True)

    def test_stop_gate_precedes_first_actual_file_replacement_and_failure_is_zero_write(self):
        manifest=deepcopy(self.manifest);manifest['releaseReady']=True;events=[]
        fence=types.SimpleNamespace(root=self.root,modified=False,confirmed=False,stop_then_unlock_database=lambda:events.append('hermes-fence'))
        original_atomic=self.base.atomic
        def atomic(path,payload,mode=0o644):
            if str(path) in {str(self.root/r['target'].lstrip('/')) for r in manifest['files']}:
                self.assertIn('marketing-stopped',events);events.append('business-write')
            return original_atomic(path,payload,mode)
        def reject(m,b,j,r):
            events.append('marketing-stop-unknown');j['marketingStopUnknown']=True;self.base.journal_write(b,j);raise ValueError('stop_unknown')
        raw=json.dumps(manifest).encode()
        with patch.object(self.base,'locks',return_value=contextlib.nullcontext()),patch.object(self.base,'live_lock',return_value=contextlib.nullcontext()),patch.object(self.base,'hermes_admission_fence',return_value=contextlib.nullcontext(fence)),patch.object(self.base,'model_release_lock',return_value=contextlib.nullcontext()),patch.object(self.base,'inspect'),patch.object(self.base,'guards'),patch.object(self.base,'retirement'),patch.object(self.base,'directory_sync'),patch.object(self.base,'atomic',side_effect=atomic),patch.object(self.base,'traffic_before_write',side_effect=reject),patch.object(self.base,'restart_for'):
            with self.assertRaisesRegex(ValueError,'stop_unknown'):self.base.apply(manifest,self.stage,sha(raw),raw,'nav-20261017T000001Z',self.root)
        self.assertNotIn('business-write',events)
        self.assertLess(events.index('hermes-fence'),events.index('marketing-stop-unknown'))

    def test_maintenance_stop_verifies_cgroup_and_never_touches_collector(self):
        contract=self.manifest['marketingStopContract'];pidfile=self.root/contract['cgroupPath'].lstrip('/');pidfile.parent.mkdir(parents=True);pidfile.write_text('123\n')
        proc=self.root/'proc/123/cgroup';proc.parent.mkdir(parents=True);proc.write_text('1:name=systemd:/system.slice/fs-marketing-range.service\n')
        active=deepcopy(contract['properties']);current=dict(active);commands=[];journal={}
        def state(unit):return dict(current) if unit==maintenance.UNIT else {'ActiveState':'inactive','MainPID':'0','ControlGroup':''}
        def stop(command,**kwargs):
            commands.append(command);self.assertEqual(command,['systemctl','stop','fs-marketing-range.service']);current.update(ActiveState='inactive',MainPID='0');pidfile.write_text('')
        with patch.object(maintenance,'state',side_effect=state),patch.object(maintenance.subprocess,'run',side_effect=stop):maintenance.stop(self.manifest,self.folder,journal,self.root,lambda *a:None)
        self.assertTrue(journal['marketingStopped']);self.assertEqual(len(commands),1)
        current.update(active);pidfile.write_text('123\n');journal={}
        with patch.object(maintenance,'state',side_effect=state),patch.object(maintenance.subprocess,'run',side_effect=subprocess.TimeoutExpired('systemctl stop',35)):
            with self.assertRaisesRegex(ValueError,'unknown_zero_replacement'):maintenance.stop(self.manifest,self.folder,journal,self.root,lambda *a:None)
        self.assertTrue(journal['marketingStopUnknown']);self.assertFalse(journal['marketingStopped'])

    def test_docker_timeout_records_unknown_and_never_retries_build(self):
        backup=self.folder/'unknown-build';backup.mkdir();journal={}
        for row in self.manifest['files']:
            if row['candidate'].startswith('session/') and not row['candidate'].endswith('.service'):
                path=self.root/row['target'].lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((self.stage/'candidate'/row['candidate']).read_bytes())
        with patch.object(leaf,'baseline'),patch.object(leaf,'archive_boundary'),patch.object(leaf.subprocess,'run',side_effect=subprocess.TimeoutExpired('docker build',120)) as run,patch.object(self.base,'directory_sync'):
            with self.assertRaisesRegex(ValueError,'unknown_requires_reconcile'):leaf.apply(self.manifest,backup,journal,self.root,self.base.atomic,lambda *a:None,self.base.digest,self.base.no_target_link)
            self.assertEqual(journal['sessionBuildOutcome'],'UNKNOWN');self.assertTrue(journal['sessionBuildIntent']);self.assertEqual(run.call_args.kwargs['timeout'],120);self.assertEqual(run.call_args.kwargs['env']['DOCKER_BUILDKIT'],'0')
            with self.assertRaisesRegex(ValueError,'previous_intent'):leaf.apply(self.manifest,backup,journal,self.root,self.base.atomic,lambda *a:None,self.base.digest,self.base.no_target_link)
            self.assertEqual(run.call_count,1)

    def test_docker_failure_keeps_private_diagnostic_and_blocks_replay(self):
        backup=self.folder/'failed-build';backup.mkdir();journal={}
        for row in self.manifest['files']:
            if row['candidate'].startswith('session/') and not row['candidate'].endswith('.service'):
                path=self.root/row['target'].lstrip('/');path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((self.stage/'candidate'/row['candidate']).read_bytes())
        failure=subprocess.CalledProcessError(1,['docker','build'],output=b'fixture stdout',stderr=b'fixture private stderr')
        with patch.object(leaf,'baseline'),patch.object(leaf,'archive_boundary'),patch.object(leaf.subprocess,'run',side_effect=failure) as run,patch.object(self.base,'directory_sync'):
            with self.assertRaisesRegex(ValueError,'failed_private_diagnostic'):leaf.apply(self.manifest,backup,journal,self.root,self.base.atomic,lambda *a:None,self.base.digest,self.base.no_target_link)
            log=Path(journal['sessionBuildDiagnostic']);self.assertIn(b'fixture private stderr',log.read_bytes());self.assertEqual(sha(log.read_bytes()),journal['sessionBuildDiagnosticSha256']);self.assertEqual(journal['sessionBuildOutcome'],'FAILED');self.assertEqual(journal['sessionBuildExitCode'],1)
            self.assertEqual(run.call_args.kwargs['env']['DOCKER_BUILDKIT'],'0');self.assertIn('SESSION_BASE_IMAGE='+leaf.BASE_IMAGE,run.call_args.args[0]);self.assertIn('--pull=false',run.call_args.args[0])
            with self.assertRaisesRegex(ValueError,'previous_intent'):leaf.apply(self.manifest,backup,journal,self.root,self.base.atomic,lambda *a:None,self.base.digest,self.base.no_target_link)
            self.assertEqual(run.call_count,1)

    def test_restoration_starts_only_coherent_code_and_health_is_readonly(self):
        contract=self.manifest['marketingStopContract'];pidfile=self.root/contract['cgroupPath'].lstrip('/');pidfile.parent.mkdir(parents=True);pidfile.write_text('')
        journal={'marketingStopped':True};commands=[]
        from urllib.error import HTTPError
        with patch.object(maintenance,'state',return_value={**contract['properties'],'ActiveState':'inactive','MainPID':'0','ControlGroup':''}),patch.object(maintenance.subprocess,'run',side_effect=lambda args,**k:commands.append(args)),patch.object(maintenance.urllib.request,'urlopen',side_effect=HTTPError('fixture',401,'denied',None,io.BytesIO())):
            maintenance.start(self.manifest,self.folder,journal,self.root,lambda *a:None)
        self.assertTrue(journal['marketingRestoredActive']);self.assertFalse(journal['marketingStopped']);self.assertEqual(commands[0],['systemctl','start',maintenance.UNIT])
        backup=self.folder/'restart-check';backup.mkdir();journal={'manifest':self.manifest,'status':'rolled-back','marketingStopped':True,'files':self.manifest['files']}
        with patch.object(self.base,'directory_sync'):self.base.journal_write(backup,journal)
        fake=types.SimpleNamespace(start=unittest.mock.Mock(side_effect=RuntimeError('observed coherent start')))
        with patch.object(bridge,'reviewed_marketing',return_value=fake):
            with self.assertRaisesRegex(RuntimeError,'observed coherent start'):self.base.restart_for(self.manifest,types.SimpleNamespace(root=self.root))
        self.assertEqual(fake.start.call_count,1)
        changed=next(row for row in self.manifest['files'] if row['beforeSha256'] is not None);(self.root/changed['target'].lstrip('/')).write_bytes(b'mixed-other-version')
        with patch.object(bridge,'reviewed_marketing',return_value=fake):
            with self.assertRaisesRegex(ValueError,'mixed_code_blocks'):self.base.restart_for(self.manifest,types.SimpleNamespace(root=self.root))
        self.assertEqual(fake.start.call_count,1)

    def test_rollback_rechecks_live_service_after_start_success_lost_journal(self):
        row=next(r for r in self.manifest['files'] if r['candidate']=='hermes/controller.py');target=self.root/row['target'].lstrip('/');new=(self.stage/'candidate'/row['candidate']).read_bytes();target.write_bytes(new)
        backup=self.folder/'crashed-start';old=backup/'files'/row['candidate'];old.parent.mkdir(parents=True);old.write_bytes(b'old-code')
        journal={'manifest':self.manifest,'approvedManifestSha256':'a'*64,'marketingStopped':True,'marketingStartIntent':True,'files':[{**row,'beforeMode':0o644,'written':True,'intent':True}]}
        contract=self.manifest['marketingStopContract'];current=dict(contract['properties']);pidfile=self.root/contract['cgroupPath'].lstrip('/');pidfile.parent.mkdir(parents=True);pidfile.write_text('123\n');proc=self.root/'proc/123/cgroup';proc.parent.mkdir(parents=True);proc.write_text('1:name=systemd:/system.slice/fs-marketing-range.service\n');commands=[]
        def state(unit):return dict(current) if unit==maintenance.UNIT else {'ActiveState':'inactive','MainPID':'0','ControlGroup':''}
        def stop(args,**kwargs):
            self.assertEqual(target.read_bytes(),new);commands.append(args);current.update(ActiveState='inactive',MainPID='0');pidfile.write_text('')
        with patch.object(maintenance,'state',side_effect=state),patch.object(maintenance.subprocess,'run',side_effect=stop),patch.object(bridge,'reviewed_marketing',return_value=maintenance),patch.object(self.base,'rollback_credentials'),patch.object(self.base,'traffic_restore'),patch.object(self.base,'directory_sync'):
            self.base.rollback_journal(backup,journal,self.root)
        self.assertEqual(commands,[['systemctl','stop',maintenance.UNIT]]);self.assertEqual(target.read_bytes(),b'old-code')
        target.write_bytes(new);current.update(ActiveState='activating',MainPID='123');journal['files'][0].update(written=True,intent=True,rollbackIntent=False)
        with patch.object(maintenance,'state',side_effect=state),patch.object(bridge,'reviewed_marketing',return_value=maintenance):
            with self.assertRaisesRegex(ValueError,'unknown_no_file_restore'):self.base.rollback_journal(backup,journal,self.root)
        self.assertEqual(target.read_bytes(),new)

    def test_marketing_health_waits_for_bind_and_keeps_exact_401_contract(self):
        from urllib.error import HTTPError,URLError
        contract=self.manifest['marketingStopContract'];pidfile=self.root/contract['cgroupPath'].lstrip('/');pidfile.parent.mkdir(parents=True);pidfile.write_text('');journal={'marketingStopped':True}
        responses=[URLError('connection refused'),HTTPError('fixture',401,'denied',None,io.BytesIO())]
        with patch.object(maintenance,'state',return_value={**contract['properties'],'ActiveState':'inactive','MainPID':'0','ControlGroup':''}),patch.object(maintenance.subprocess,'run'),patch.object(maintenance.urllib.request,'urlopen',side_effect=responses) as opened,patch.object(maintenance.time,'sleep'):
            maintenance.start(self.manifest,self.folder,journal,self.root,lambda *a:None)
        self.assertEqual(opened.call_count,2);self.assertTrue(journal['marketingRestoredActive']);self.assertEqual(journal['marketingHealth'],'anonymous_401')
        journal={}
        with patch.object(maintenance,'state',return_value={**contract['properties'],'ActiveState':'inactive','MainPID':'0','ControlGroup':''}),patch.object(maintenance.subprocess,'run'),patch.object(maintenance.urllib.request,'urlopen',side_effect=HTTPError('fixture',403,'denied',None,io.BytesIO())):
            with self.assertRaisesRegex(ValueError,'denial_contract'):maintenance.start(self.manifest,self.folder,journal,self.root,lambda *a:None)
        self.assertTrue(journal['marketingStartUnknown'])

    def test_unit_content_drift_blocks_stop_even_when_systemd_properties_match(self):
        contract=self.manifest['marketingStopContract'];unit=self.root/contract['properties']['FragmentPath'].lstrip('/');unit.write_bytes(b'external-new-unit-content')
        with patch.object(maintenance,'state',return_value=contract['properties']),patch.object(maintenance.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'unit_source_sha_drift'):maintenance.stop(self.manifest,self.folder,{},self.root,lambda *a:None,rollback=True)
        run.assert_not_called()

    def test_stop_success_lost_stopped_flag_reconciles_without_file_intent(self):
        backup=self.folder/'stop-success-crash';backup.mkdir();rows=[]
        for row in self.manifest['files']:
            rows.append({**row,'beforeMode':0o644,'written':False,'intent':False})
            if row['beforeSha256'] is not None:
                saved=backup/'files'/row['candidate'];saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes((self.root/row['target'].lstrip('/')).read_bytes())
        journal={'manifest':self.manifest,'approvedManifestSha256':'a'*64,'marketingStopIntent':True,'marketingStopped':False,'files':rows}
        contract=self.manifest['marketingStopContract'];pidfile=self.root/contract['cgroupPath'].lstrip('/');pidfile.parent.mkdir(parents=True);pidfile.write_text('')
        fake=types.SimpleNamespace(ensure_stopped=maintenance.ensure_stopped,start=unittest.mock.Mock(side_effect=RuntimeError('observed restore after confirmed stop')))
        with patch.object(maintenance,'state',return_value={**contract['properties'],'ActiveState':'inactive','MainPID':'0','ControlGroup':''}),patch.object(bridge,'reviewed_marketing',return_value=fake),patch.object(self.base,'rollback_credentials'),patch.object(self.base,'traffic_restore'),patch.object(self.base,'directory_sync'):
            self.base.rollback_journal(backup,journal,self.root)
            self.assertTrue(journal['marketingStopped']);self.assertEqual(journal['status'],'rolled-back')
            with self.assertRaisesRegex(RuntimeError,'observed restore after confirmed stop'):self.base.restart_for(self.manifest,types.SimpleNamespace(root=self.root))
        self.assertEqual(fake.start.call_count,1)

    def test_inactive_unit_fingerprint_drift_blocks_confirm_and_start(self):
        contract=self.manifest['marketingStopContract'];(self.root/contract['properties']['FragmentPath'].lstrip('/')).write_bytes(b'changed while stopped')
        state={**contract['properties'],'ActiveState':'inactive','MainPID':'0','ControlGroup':''}
        with patch.object(maintenance,'state',return_value=state),patch.object(maintenance.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'unit_source_sha_drift'):maintenance.ensure_stopped(self.manifest,self.folder,{},self.root,lambda *a:None)
            with self.assertRaisesRegex(ValueError,'unit_source_sha_drift'):maintenance.start(self.manifest,self.folder,{},self.root,lambda *a:None)
        run.assert_not_called()

    def test_successful_manual_full_rollback_refused_but_interrupted_recovery_remains(self):
        backup=self.folder/'manual-status-gate';backup.mkdir();journal=backup/'journal.json'
        journal.write_text(json.dumps({'status':'applied-awaiting-actual-http-role-acceptance'}),encoding='utf-8')
        with patch.object(self.base,'locks',return_value=contextlib.nullcontext()),patch.object(self.base,'rollback_credentials') as credentials:
            with self.assertRaisesRegex(ValueError,'completed_release_manual_full_rollback_refused'):self.base.rollback(backup,'a'*64,self.root)
        credentials.assert_not_called()
        journal.write_text(json.dumps({'status':'prepared'}),encoding='utf-8')
        with patch.object(self.base,'locks',return_value=contextlib.nullcontext()),patch.object(self.base,'rollback_credentials',side_effect=RuntimeError('existing interrupted recovery reached')) as credentials:
            with self.assertRaisesRegex(RuntimeError,'existing interrupted recovery reached'):self.base.rollback(backup,'a'*64,self.root)
        credentials.assert_called_once()

    def test_release_ready_false_prevents_mutation(self):
        raw=json.dumps(self.manifest).encode()
        with patch.object(self.base,'locks') as locks:
            with self.assertRaisesRegex(ValueError,'releaseReady=false'):self.base.apply(self.manifest,self.stage,sha(raw),raw,'nav-20261017T000000Z',self.root)
        locks.assert_not_called()

if __name__=='__main__':unittest.main()
