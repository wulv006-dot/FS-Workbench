import copy,hashlib,importlib.util,json
from pathlib import Path
import tempfile,unittest
from unittest import mock
from types import SimpleNamespace

p=Path(__file__).resolve().parents[1]/'deploy/routes_release.py'
s=importlib.util.spec_from_file_location('routes_scope',p);scope=importlib.util.module_from_spec(s);s.loader.exec_module(scope)


class Routes(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.stage=Path(self.temp.name)
        self.before=dict(contract='fs-knowledge-load-policy-v1',requests={},native={'enabled':True,'readonly_sessions':{'original':{'task_ids':['original']}}})
        self.item=dict(owner='wulv',project='FS',channel='fs',task_types=['report','data','conversation'],modules=['FS','FC27'],
            catalog='knowledge-releases/hermes-learning-closure-20261023-1/index.json',sha256='a'*64,
            baseline_compatibility={'mode':'retain_full_baseline','sha256':'b'*64},reviewed_skills={'source':'approved_current'})
        self.after=dict(self.before,task_routes={'enabled':True,'routes':[self.item]})
        (self.stage/'candidate/policy').mkdir(parents=True)
        self.value=dict(scope=scope.SCOPE,businessWrites=False,timersChanged=False,files=[dict(candidate=next(iter(scope.TARGETS)),target=next(iter(scope.TARGETS.values())))],
            catalogPath=self.item['catalog'],catalogSha256='a'*64,baselineSha256='b'*64,
            nativeImageRequired='sha256:'+'c'*64,nativeImageBefore='sha256:'+'c'*64,nativeImageAfter='sha256:'+'c'*64,
            nativeUnits=['fs-hermes-desktop.service','hermes-dingtalk.service'],nativeSQLiteVersion='3.53.4')
    def write(self):
        before=json.dumps(self.before).encode();after=json.dumps(self.after).encode()
        (self.stage/'before-policy.json').write_bytes(before);(self.stage/'candidate/policy/knowledge-load-policy.json').write_bytes(after)
        self.value['files'][0].update(beforeSha256=hashlib.sha256(before).hexdigest(),sha256=hashlib.sha256(after).hexdigest())
        self.value['taskRoutesSha256']=scope.digest(self.after['task_routes']['routes'])
    def test_only_new_task_routes_change_and_original_readonly_remains(self):
        self.write();scope.checked(self.value,self.stage)
        self.assertEqual(self.after['native'],self.before['native'])
    def test_other_targets_business_flags_and_policy_sections_are_refused(self):
        self.write()
        for key in ('businessWrites','timersChanged'):
            with self.assertRaisesRegex(ValueError,'exact_policy_scope'):scope.checked(dict(self.value,**{key:True}),self.stage)
        self.after['native']={'enabled':False};self.write()
        with self.assertRaisesRegex(ValueError,'existing_policy_preserved'):scope.checked(self.value,self.stage)
    def test_identity_hash_or_fs_baseline_cannot_be_changed(self):
        self.write();self.value['taskRoutesSha256']='0'*64
        with self.assertRaisesRegex(ValueError,'approved_identities'):scope.checked(self.value,self.stage)
        self.after['task_routes']['routes'][0]['baseline_compatibility']['sha256']='0'*64;self.write()
        with self.assertRaisesRegex(ValueError,'full_baseline'):scope.checked(self.value,self.stage)
    def test_feishu_requires_exact_profile_chat_thread_and_type(self):
        self.item.update(owner='fixture-user',channel='feishu',profile_name='default',chat_id='fixture-group',thread_id=None,task_types=['conversation'])
        self.write();scope.checked(self.value,self.stage)
        for key in ('owner','profile_name','chat_id','thread_id'):
            changed=copy.deepcopy(self.item);changed.pop(key);self.after['task_routes']['routes']=[changed];self.write()
            with self.assertRaisesRegex(ValueError,'feishu_exact_scope'):scope.checked(self.value,self.stage)
    def test_policy_bytes_and_catalog_cannot_drift(self):
        self.write();(self.stage/'before-policy.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'frozen_policy_bytes'):scope.checked(self.value,self.stage)
        self.item['modules']=['D4'];self.write()
        with self.assertRaisesRegex(ValueError,'published_catalog'):scope.checked(self.value,self.stage)

    def test_activation_requires_same_image_native_restart(self):
        self.write();self.value['nativeImageAfter']='sha256:'+'d'*64
        with self.assertRaisesRegex(ValueError,'same_image_cache_restart'):scope.checked(self.value,self.stage)

    def refresh(self):
        self.before=copy.deepcopy(self.after)
        self.before['task_routes']['routes'][0].update(catalog='old',sha256='0'*64,entry_ids=['old'])
        self.item['entry_ids']=['current'];self.item['history_entry_ids']=['archive']
        plugin=self.stage/'candidate/plugin/knowledge.py';plugin.parent.mkdir();plugin.write_bytes(b'new plugin')
        self.value.update(knowledgeRefresh=True)
        self.value['files'].append(dict(candidate='plugin/knowledge.py',target='/var/lib/fs-hermes-fc/profile/plugins/fs-readonly/knowledge.py',
            beforeSha256='d'*64,sha256=hashlib.sha256(plugin.read_bytes()).hexdigest()))
        self.write()

    def test_refresh_changes_versions_with_exact_existing_bindings_and_original_readonly(self):
        self.refresh();scope.checked(self.value,self.stage)
        self.item['owner']='other';self.write()
        with self.assertRaisesRegex(ValueError,'refresh_existing_bindings'):scope.checked(self.value,self.stage)
        self.item['owner']='wulv';self.after['native']=dict(enabled=False);self.write()
        with self.assertRaisesRegex(ValueError,'existing_policy_preserved'):scope.checked(self.value,self.stage)

    def test_refresh_can_add_only_declared_desktop_owner_and_keeps_group_scope(self):
        self.refresh()
        desktop=dict(self.item,channel='desktop',profile_name='default',task_types=['conversation'])
        desktop.pop('baseline_compatibility');self.after['task_routes']['routes'].append(desktop);self.write()
        with self.assertRaisesRegex(ValueError,'refresh_existing_bindings'):scope.checked(self.value,self.stage)
        self.value['desktopRouteAdded']=True;scope.checked(self.value,self.stage)
        desktop['owner']='other';self.write()
        with self.assertRaisesRegex(ValueError,'desktop_exact_owner_profile'):scope.checked(self.value,self.stage)

    def test_refresh_plugin_payload_drift_is_rejected(self):
        self.refresh();(self.stage/'candidate/plugin/knowledge.py').write_bytes(b'unreviewed')
        with self.assertRaisesRegex(ValueError,'refresh_plugin_bytes'):scope.checked(self.value,self.stage)
        self.value['releaseReady']=True
        with self.assertRaisesRegex(ValueError,'refresh_protection_required'):scope.checked(self.value,self.stage)

    def test_refresh_reuses_frozen_profile_adapter_and_native_fence(self):
        self.refresh()
        root=p.parents[4]
        sources={'release_adapter_base.py':'releases/fs-dashboard/user-analytics-20261022/deploy/release.py',
                 'release_navigation_base.py':'releases/fs-dashboard/channel-effects-20261021/deploy/release_navigation_base.py',
                 'native_scope_base.py':'releases/fs-dashboard/knowledge-layering-20261023/deploy/native_release.py'}
        for target,source in sources.items():
            raw=(root/source).read_bytes()
            (self.stage/target).write_bytes(raw if target=='release_navigation_base.py' else raw.replace(b'\r\n',b'\n'))
        for row in self.value['files']:row.update(owner='0:0',mode='0o644')
        (self.stage/'approved-manifest.json').write_text(json.dumps(self.value))
        with mock.patch.object(scope,'HERE',self.stage):
            base=scope.load_base()
        self.assertEqual(base.apply.__module__,'frozen_hermes_v2_publisher')
        self.assertEqual(base.hermes_admission_fence.__name__,'fence')

    def test_existing_native_fence_recreates_gateway_cache_and_keeps_business_reader(self):
        path=p.parents[2]/'knowledge-layering-20261023/deploy/native_release.py'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),scope.NATIVE_SCOPE_SHA)
        spec=importlib.util.spec_from_file_location('routes_test_native',path)
        native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
        events=[]
        class Fence:
            def __init__(self,root):self.root=root;events.append('admission_locked')
            def close(self):events.append('admission_unlocked')
        db=mock.Mock();db.rollback.side_effect=lambda:events.append('native_db_unlocked')
        base=SimpleNamespace(HermesAdmissionFence=Fence,rollback_journal=lambda *a:None,
                             rooted=lambda root,name:root/name.lstrip('/'))
        native.install_native_scope(base,self.value)
        unit=self.stage/'etc/systemd/system/fs-hermes-desktop.service';unit.parent.mkdir(parents=True)
        unit.write_text('ExecStart=docker run '+self.value['nativeImageRequired'])
        def run(args,**kwargs):events.append(tuple(args))
        def output(args,**kwargs):
            return 'ActiveState=inactive\n' if args[0]=='systemctl' else self.value['nativeImageRequired']+'\n'
        with mock.patch.object(native,'acquire_native_database',return_value=db),mock.patch.object(native.subprocess,'run',side_effect=run),\
                mock.patch.object(native.subprocess,'check_output',side_effect=output),mock.patch.object(native,'wait_for_native_container') as wait:
            with base.hermes_admission_fence(self.value,self.stage) as fence:
                base.restart_for(self.value,fence)
            with self.assertRaisesRegex(ValueError,'admission_fence_required'):base.restart_for(self.value)
        wait.assert_called_once_with(self.value['nativeImageRequired'])
        stop=('systemctl','stop','hermes-dingtalk.service','fs-hermes-desktop.service')
        start=('systemctl','start','fs-hermes-desktop.service')
        self.assertLess(events.index(stop),events.index('native_db_unlocked'))
        self.assertLess(events.index('native_db_unlocked'),events.index(start))
        self.assertLess(events.index(start),events.index(('systemctl','start','hermes-dingtalk.service')))
        self.assertEqual(events[-1],'admission_unlocked')
        self.assertFalse(any(isinstance(e,tuple) and 'fs-business-range.service' in e for e in events))


if __name__=='__main__':unittest.main()
