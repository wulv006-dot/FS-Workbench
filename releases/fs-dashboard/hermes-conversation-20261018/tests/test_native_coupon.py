"""Real native binding, original IAM and coupon ledger; only Admin transport is synthetic."""
import ast
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import test_native_user_data as native_user

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
BACKEND=HERE.parents[1]/'campaign-analytics-20261023/backend'
sys.path.insert(0,str(BACKEND))
spec=importlib.util.spec_from_file_location('coupon_original_fixture',BACKEND/'tests/test_benefit_operations.py')
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)


class NativeCouponIntentTests(unittest.TestCase):
    make= native_user.NativeUserRelay.make
    load= native_user.NativeUserRelay.load
    bind= native_user.NativeUserRelay.bind
    call= native_user.NativeUserRelay.call

    def setUp(self):
        NativeCouponTests.setUp(self)
        self.now=datetime.now(timezone.utc)
        created=self.conversation.store.create('operator');self.cid,self.sid=created['conversation_id'],created['session_id']
        self.text='  Execute fs_grant_coupon with operation_id=synthetic-intent-operation only.  '
        self.client_id='intent_original_request'
        turn=self.conversation.submit('operator',self.cid,self.text,self.client_id)
        self.turn_id=turn['turn_id']
        from campaign_backend.benefits import row_hash
        import hashlib
        self.intent=dict(intent=dict(owner='operator',conversation_id=self.cid,session_id=self.sid,
            input_sha256=hashlib.sha256(self.text.encode()).hexdigest()),
            request=dict(action='coupon_grant',site_id='266',kind='coupon',native_id='123',
                operation_id='synthetic-intent-operation',before_hash=row_hash(self.row),
                grant_batch_no='synthetic-intent-batch',email='one@example.test'),
            valid_from=(self.now-timedelta(minutes=1)).isoformat(),valid_until=(self.now+timedelta(minutes=10)).isoformat(),
            authority_ref='synthetic-existing-user-authorization')
        self.requests=[];self.transitions=[];self.final_writes=[];self.fail_write=False
        def request(*args,**kw):
            self.requests.append(args)
            return 202,{'run_id':'run_'+'c'*32}
        self.conversation._request=request

    @contextmanager
    def root_file(self,record):
        import conversation_user_data as module
        import secrets
        path=Path(self.temp.name)/'approval/native-coupon-approval.json';path.parent.mkdir(exist_ok=True)
        if record is not None:path.write_text(json.dumps(record),encoding='utf8');path.chmod(0o600)
        real_lstat=Path.lstat;real_fstat=os.fstat
        def view(info,directory=False):
            values={k:getattr(info,k) for k in dir(info) if k.startswith('st_')}
            values.update(st_uid=0,st_gid=0,st_mode=(stat.S_IFDIR|0o755) if directory else stat.S_IFREG|0o600)
            if os.name=='nt':values['st_ctime_ns']=info.st_mtime_ns
            return SimpleNamespace(**values)
        def lstat(p,*a,**kw):
            info=real_lstat(p,*a,**kw)
            return view(info,p in path.parents) if p==path or p in path.parents else info
        def fstat(fd):
            info=real_fstat(fd)
            if path.exists():
                current=real_lstat(path)
                if (info.st_dev,info.st_ino)==(current.st_dev,current.st_ino):return view(info)
            return info
        # Execute the actual existing atomic writer, not a synthetic approval write.
        controller=sys.modules['controller'];source=HERE.parents[1]/'hermes-v2-core-20261020/source/controller.py'
        node=next(n for n in ast.parse(source.read_text('utf8')).body if isinstance(n,ast.FunctionDef) and n.name=='atomic')
        namespace=dict(Path=Path,secrets=secrets,json=json)
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        admission_path=self.conversation.run_root/'admissions'/(self.sid+'.json')
        reference_path=self.conversation.store.path.parent/'knowledge'/hashlib.sha256(b'operator').hexdigest()/(self.turn_id+'.json')
        def atomic(destination,value,**kw):
            destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
            if destination==path:
                admission=json.loads((self.conversation.run_root/'admissions'/(self.sid+'.json')).read_bytes())
                bound=value['binding'];row=self.conversation.native.row('operator',self.cid,self.turn_id)
                self.assertFalse(admission['ready']);self.assertEqual(row['binding'],bound)
                self.assertTrue(bound['run_id']);self.assertIn(self.turn_id,self.conversation.hermes.gateways)
                self.assertIn(self.turn_id,self.conversation.live);self.assertEqual(len(self.requests),1)
                self.final_writes.append(deepcopy(value))
                if self.fail_write:raise OSError('synthetic approval write failure')
            elif destination==admission_path:
                self.assertIn('ready',value)
                self.assertEqual(kw.get('mode',0o640),0o640)
                self.transitions.append(value['ready'])
            namespace['atomic'](destination,value,**kw)
            if destination==reference_path:
                self.assertEqual(kw.get('mode'),0o600)
                self.assertEqual(json.loads(destination.read_bytes()),value)
                if os.name=='posix':
                    self.assertEqual(stat.S_IMODE(destination.stat().st_mode),0o600)
                    self.assertEqual(stat.S_IMODE(destination.parent.stat().st_mode),0o700)
            elif destination==admission_path and os.name=='posix':
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode),0o640)
        with patch.object(module,'CAMPAIGN_APPROVAL_FILE',path),patch.object(Path,'lstat',lstat),patch.object(os,'fstat',fstat),patch.object(controller,'atomic',atomic):
            if os.name=='nt':
                # Linux exercises the real no-follow FD/flock. Windows cannot
                # replace an open target; only this OS locking boundary is a fixture.
                with patch.object(module,'_campaign_approval_lock',lambda expected:__import__('contextlib').nullcontext(),create=True):yield path
            else:yield path

    def dispatch(self):
        return self.conversation._dispatch('operator',self.cid,self.turn_id,self.sid,self.text,self.client_id)

    def test_real_dispatch_finalizes_stored_binding_before_ready_and_is_idempotent(self):
        import conversation_user_data as module
        with self.root_file(self.intent) as path:
            self.dispatch()
            value=json.loads(path.read_bytes())
            self.assertEqual(set(value),{'binding','request','valid_from','valid_until','authority_ref'},
                'dispatch released worker without finalizing the matching intent')
            self.assertEqual(value['request'],self.intent['request']);self.assertEqual(self.transitions,[False,True])
            bound=self.conversation.native.row('operator',self.cid,self.turn_id)['binding']
            self.assertEqual(value['binding'],bound);self.assertEqual(len(self.final_writes),1)
            self.assertEqual(self.requests[0][2],{'input':self.text,'session_id':self.sid})
            before=path.read_bytes();inode=path.stat().st_ino
            self.assertTrue(module.prepare_campaign_approval(self.conversation.native,bound))
            from conversation_native import NativeConversation
            restarted=NativeConversation(self.conversation)
            self.assertTrue(module.prepare_campaign_approval(restarted,bound))
            self.dispatch()
            self.assertEqual((path.read_bytes(),path.stat().st_ino),(before,inode))
            self.assertEqual(len(self.requests),1);self.assertEqual(len(self.final_writes),1)
            # The first actual host tool consumes the just-finalized file, not
            # the unrelated pre-bound callback fixture from setUp.
            self.data.campaign.approval_source=module.campaign_approval
            args={'operation_id':self.intent['request']['operation_id']}
            receipt=self.call('fs_grant_coupon',args,binding=bound)
            self.assertTrue(receipt['business_confirmed']);self.assertEqual(len(self.posts),1)
            self.assertEqual(self.call('fs_grant_coupon',args,binding=bound),receipt)
            self.assertEqual(len(self.posts),1)

    @contextmanager
    def clean_campaign_imports(self):
        # Map only the deployed absolute mount for the local OS fixture. Real
        # campaign imports/validation/ledger and final Admin stub remain intact.
        loaded={k:v for k,v in sys.modules.items() if k=='campaign_backend' or k.startswith('campaign_backend.')}
        class RuntimePaths(list):
            inserted=[]
            def insert(self,index,value):
                self.inserted.append(value)
                super().insert(index,str(BACKEND) if value=='/opt/fs-campaign-dashboard/backend' else value)
        paths=RuntimePaths(p for p in sys.path if 'campaign-analytics-20261023' not in str(p))
        for name in loaded:del sys.modules[name]
        try:
            with patch.object(sys,'path',paths):yield paths
        finally:
            for name in list(sys.modules):
                if name=='campaign_backend' or name.startswith('campaign_backend.'):del sys.modules[name]
            sys.modules.update(loaded)

    def test_clean_import_dispatch_finalizes_before_ready_and_original_grant_posts_once(self):
        with self.clean_campaign_imports() as paths:
            self.assertNotIn('campaign_backend',sys.modules)
            self.test_real_dispatch_finalizes_stored_binding_before_ready_and_is_idempotent()
            self.assertIn('/opt/fs-campaign-dashboard/backend',paths.inserted)
            self.assertEqual(len(self.posts),1)

    def test_unmatched_intent_does_not_assemble_campaign_modules(self):
        self.intent['intent']['conversation_id']='0'*32
        with self.clean_campaign_imports() as paths,self.root_file(self.intent):
            self.dispatch()
            self.assertEqual(self.transitions,[False,True])
            self.assertEqual(paths.inserted,[])
            self.assertNotIn('campaign_backend',sys.modules)
            self.assertEqual(self.posts,[])

    def test_matching_expired_or_invalid_intent_never_releases_or_reposts(self):
        self.intent['valid_until']=self.now.isoformat()
        with self.root_file(self.intent) as path:
            before=path.read_bytes()
            with self.assertRaisesRegex(PermissionError,'business_authorization_expired'):self.dispatch()
            row=self.conversation.native.row('operator',self.cid,self.turn_id)
            self.assertEqual((row['binding']['run_id'],row['stopped']),('run_'+'c'*32,1))
            self.assertEqual(self.conversation.store.detail('operator',self.cid)['turns'][0]['state'],'dispatch_unknown')
            self.assertNotIn(True,self.transitions);self.assertEqual(path.read_bytes(),before)
            self.dispatch();self.assertEqual(len(self.requests),1)

    def test_matching_atomic_failure_preserves_original_run_and_ready_false(self):
        self.fail_write=True
        with self.root_file(self.intent) as path:
            before=path.read_bytes()
            with self.assertRaisesRegex(OSError,'synthetic approval write failure'):self.dispatch()
            self.assertNotIn(True,self.transitions);self.assertEqual(path.read_bytes(),before)
            self.dispatch();self.assertEqual(len(self.requests),1)

    def test_other_or_broken_approval_is_not_an_ordinary_chat_prerequisite(self):
        import conversation_user_data as module
        original=deepcopy(self.intent)
        for key in ('owner','conversation_id','session_id','input_sha256'):
            with self.subTest(key=key):
                self.intent=deepcopy(original);self.intent['intent'][key]='different'
                # Each case uses the same un-dispatched original turn; the
                # private producer itself must decline without consuming it.
                with self.root_file(self.intent) as path:
                    before=path.read_bytes()
                    self.assertFalse(module.prepare_campaign_approval(self.conversation.native,
                        dict(self.binding,conversation_id=self.cid,session_id=self.sid,turn_id=self.turn_id)))
                    self.assertEqual(path.read_bytes(),before)
                path.unlink();path.parent.rmdir()
        self.intent=original
        with self.root_file(None) as path:
            path.write_text('{broken',encoding='utf8')
            self.dispatch();self.assertEqual(self.transitions,[False,True]);self.assertEqual(len(self.requests),1)

    def test_matching_file_drift_or_lock_refusal_never_releases_ready(self):
        import conversation_user_data as module
        with self.root_file(self.intent) as path:
            @contextmanager
            def changed(expected):
                value=json.loads(path.read_bytes());value['request']['grant_batch_no']='unapproved-drift'
                path.write_text(json.dumps(value),encoding='utf8')
                yield
            with patch.object(module,'_campaign_approval_lock',changed),self.assertRaisesRegex(PermissionError,'business_authorization_file_changed'):
                self.dispatch()
            self.assertNotIn(True,self.transitions);self.assertEqual(self.final_writes,[])
            self.dispatch();self.assertEqual(len(self.requests),1)

    def test_final_record_cannot_rebind_to_another_original_run(self):
        import conversation_user_data as module
        with self.root_file(self.intent) as path:
            self.dispatch();before=path.read_bytes()
            actual=self.conversation.native.row('operator',self.cid,self.turn_id)['binding']
            for changed in ({'run_id':'run_'+'d'*32},{'lease':'d'*32},{'turn_id':'d'*32}):
                self.assertFalse(module.prepare_campaign_approval(self.conversation.native,dict(actual,**changed)))
            self.assertEqual(path.read_bytes(),before);self.assertEqual(len(self.final_writes),1)

    def test_matching_lock_holder_cannot_be_overtaken(self):
        import conversation_user_data as module
        with self.root_file(self.intent) as path:
            before=path.read_bytes()
            if os.name=='posix':
                import fcntl
                with path.open('rb') as holder:
                    fcntl.flock(holder.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                    with self.assertRaisesRegex(PermissionError,'business_authorization_file_locked'):self.dispatch()
            else:
                @contextmanager
                def busy(expected):
                    raise PermissionError('business_authorization_file_locked')
                    yield
                with patch.object(module,'_campaign_approval_lock',busy),self.assertRaisesRegex(PermissionError,'business_authorization_file_locked'):
                    self.dispatch()
            self.assertEqual(path.read_bytes(),before);self.assertNotIn(True,self.transitions)
            self.dispatch();self.assertEqual(len(self.requests),1)

    def test_matching_invalid_recipient_is_not_finalized(self):
        self.intent['request']['email']='one@example.test two@example.test'
        with self.root_file(self.intent) as path:
            before=path.read_bytes()
            with self.assertRaisesRegex(PermissionError,'business_authorization_mismatch'):self.dispatch()
            self.assertEqual(path.read_bytes(),before);self.assertEqual(self.final_writes,[]);self.assertNotIn(True,self.transitions)

    def test_permission_revoked_after_202_is_checked_before_finalizing(self):
        original=self.conversation._request
        def request(*args,**kw):
            result=original(*args,**kw)
            self.iam['bindings']['operator']['roles']=['Viewer'];self.policy_path.write_text(json.dumps(self.iam))
            return result
        self.conversation._request=request
        with self.root_file(self.intent) as path:
            before=path.read_bytes()
            with self.assertRaisesRegex(PermissionError,'native_campaign_access_denied'):self.dispatch()
            self.assertEqual(path.read_bytes(),before);self.assertNotIn(True,self.transitions)


class NativeCouponTests(unittest.TestCase):
    make=native_user.NativeUserRelay.make
    load=native_user.NativeUserRelay.load
    bind=native_user.NativeUserRelay.bind
    call=native_user.NativeUserRelay.call

    def setUp(self):
        native_user.NativeUserRelay.setUp(self)
        from conversation_user_data import NativeUserData,NativeCouponActions
        from campaign_backend.adapters import AdminRead
        from campaign_backend.services import BackendServices
        from conversation_user_data import authorize_campaign
        spec=importlib.util.spec_from_file_location('rbac',ROOT/'opt/fs-access-policy/rbac.py')
        self.rbac=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.rbac)
        self.module_patch=patch.dict(sys.modules,{'rbac':self.rbac});self.module_patch.start();self.addCleanup(self.module_patch.stop)
        self.policy_path=Path(self.temp.name)/'iam.json'
        self.iam=self.rbac.default_policy();self.iam['bindings']={'operator':{'roles':['PlatformAdmin']},'keeper':{'roles':['PlatformAdmin']}}
        self.policy_path.write_text(json.dumps(self.iam));self.rbac.LIVE_POLICY=str(self.policy_path)
        self.row=fixture.native_row();self.posts=[];self.reads=[];self.timeout=False;self.approval=None
        test=self
        class Session:
            token='synthetic-not-a-real-key'
            @property
            def admin(self):return self
            def get_adapter(self,url):return type('Retries',(),{'max_retries':type('Retry',(),{'total':0})()})()
            def get_admin(self,route,**params):
                test.reads.append((route,params))
                data={'list':[deepcopy(test.row)],'total':1} if route.endswith('/index') else {'row':deepcopy(test.row)}
                return 200,{'code':1,'data':data}
            def post(self,url,**kwargs):
                test.posts.append((url,kwargs))
                if url.endswith('/market.CouponGrant/import'):
                    payload=dict(code=1,data=dict(mode='sync',success=1,rows=[dict(
                        email=kwargs['json']['emails'],status='opaque-native-status',member_id=321,member_coupon_id=456)]))
                    return type('Response',(),{'status_code':200,'content':json.dumps(payload).encode()})()
                test.row.update(kwargs['json'])
                if test.timeout:raise TimeoutError('synthetic unknown')
                return type('Response',(),{'status_code':200,'content':b'{"code":1,"msg":"ok"}'})()
            def close(self):pass
        self.now=datetime(2026,11,3,12,tzinfo=timezone.utc)
        self.backend=BackendServices(Path(self.temp.name)/'campaign',fixture.policy())
        self.data=NativeUserData(self.conversation.native,self.original)
        self.data.campaign=NativeCouponActions(self.conversation.native,self.backend,lambda:AdminRead(Session()),
            authorize=authorize_campaign,approval_source=lambda binding,ident:deepcopy(self.approval),clock=lambda:self.now)
        self.conversation.native.user_data=self.data

    def grant(self):
        from campaign_backend.benefits import row_hash
        request=dict(action='benefit_edit',site_id='266',kind='coupon',native_id='123',
                     operation_id='synthetic-coupon-operation',before_hash=row_hash(self.row),
                     changes={'brief':'FS Hermes stage3 acceptance; no issuance.'})
        self.approval=dict(binding=deepcopy(self.binding),request=request,
            valid_from=(self.now-timedelta(minutes=1)).isoformat(),valid_until=(self.now+timedelta(minutes=1)).isoformat(),authority_ref='synthetic-external-approval')
        return dict(native_id='123',operation_id=request['operation_id'],before_hash=request['before_hash'],brief=request['changes']['brief'])

    def issuance(self):
        from campaign_backend.benefits import row_hash
        request=dict(action='coupon_grant',site_id='266',kind='coupon',native_id='123',
            operation_id='synthetic-issuance-operation',before_hash=row_hash(self.row),
            grant_batch_no='synthetic-reviewed-batch',email='one@example.test')
        self.approval=dict(binding=deepcopy(self.binding),request=request,
            valid_from=(self.now-timedelta(minutes=1)).isoformat(),valid_until=(self.now+timedelta(minutes=1)).isoformat(),
            authority_ref='synthetic-real-user-source-reference')
        return {'operation_id':request['operation_id']}

    def test_grant_uses_private_exact_approval_and_original_ledger_once(self):
        import conversation_user_data as module
        self.assertIn('fs_grant_coupon',module.COUPON_TOOLS,'normal native lacks reviewed grant consumer')
        self.row['status']=1  # Actual grant selector is fetch_scene, not the brief editor gate.
        args=self.issuance();approved=deepcopy(self.approval);self.approval=None
        with self.assertRaisesRegex(PermissionError,'business_authorization_required'):self.call('fs_grant_coupon',args)
        self.assertEqual(self.posts,[]);self.approval=approved
        result=self.call('fs_grant_coupon',args)
        self.assertTrue(result['business_confirmed']);self.assertEqual(self.call('fs_grant_coupon',args),result)
        self.assertTrue(self.call('fs_coupon_operation',args)['business_confirmed'])
        self.assertEqual(len(self.posts),1)
        output=json.dumps(result)
        for private in ('one@example.test','member-coupon:456','member_id','member_coupon_id'):
            self.assertNotIn(private,output)

    def test_grant_rejects_model_recipient_and_wrong_binding_or_expired_authority(self):
        import conversation_user_data as module
        self.assertIn('fs_grant_coupon',module.COUPON_TOOLS,'normal native lacks reviewed grant consumer')
        args=self.issuance();approved=deepcopy(self.approval)
        for change in ({'email':'other@example.test'},{'actor':'other'},{'native_id':'124'},
                       {'grant_batch_no':'another'},{'approved':True}):
            with self.subTest(fields=list(change)),self.assertRaises(ValueError):self.call('fs_grant_coupon',dict(args,**change))
        for key in self.binding:
            self.approval=deepcopy(approved);self.approval['binding'][key]='wrong'
            with self.subTest(binding=key),self.assertRaises(PermissionError):self.call('fs_grant_coupon',args)
        self.approval=deepcopy(approved);self.approval['valid_until']=self.now.isoformat()
        with self.assertRaises(PermissionError):self.call('fs_grant_coupon',args)
        self.approval=approved;self.iam['bindings']['operator']['roles']=['Viewer'];self.policy_path.write_text(json.dumps(self.iam))
        with self.assertRaises(PermissionError):self.call('fs_grant_coupon',args)
        self.assertEqual(self.posts,[])

    def test_grant_expiring_during_template_read_cannot_post(self):
        args=self.issuance();calls=[]
        def clock():
            calls.append(True)
            return self.now if len(calls)<=3 else self.now+timedelta(minutes=2)
        self.data.campaign.clock=clock
        result=self.call('fs_grant_coupon',args)
        self.assertEqual((result['state'],result['dispatch_state']),('rejected','not_started'))
        self.assertFalse(result['business_confirmed']);self.assertEqual(self.posts,[])

    def test_real_host_IAM_service_and_ledger_require_exact_external_approval(self):
        page=self.call('fs_coupon_candidates',{'page':1,'limit':1})
        self.assertEqual(page['items'][0]['native_id'],'123');self.assertFalse(page['complete'])
        detail=self.call('fs_coupon_detail',{'native_id':'123'})
        self.assertNotIn('SECRET',json.dumps(detail));self.assertNotIn('Description',json.dumps(detail))
        args=self.grant();approval=self.approval;self.approval=None
        with self.assertRaisesRegex(PermissionError,'business_authorization_required'):self.call('fs_edit_coupon_brief',args)
        self.assertEqual(self.posts,[])
        self.approval=approval
        result=self.call('fs_edit_coupon_brief',args)
        self.assertTrue(result['business_confirmed']);self.assertEqual(result['state'],'confirmed')
        self.assertEqual(self.call('fs_edit_coupon_brief',args),result);self.assertEqual(len(self.posts),1)
        self.assertEqual(self.row,{**fixture.native_row(),'brief':args['brief']})
        self.assertEqual(self.call('fs_coupon_operation',{'operation_id':args['operation_id']})['payload_hash'],result['payload_hash'])

    def test_revoked_actor_scope_and_expired_or_changed_approval_reject_before_post(self):
        args=self.grant();original=deepcopy(self.approval)
        for key,value in (('owner','other'),('conversation_id','wrong'),('lease','wrong')):
            bound=dict(self.binding,**{key:value})
            with self.assertRaises((PermissionError,LookupError)):self.call('fs_coupon_detail',{'native_id':'123'},bound)
        for change in ({'native_id':'124'},{'brief':'unapproved'},{'actor':'other'},{'site_id':'0'}):
            with self.subTest(change=change),self.assertRaises((PermissionError,ValueError)):
                self.call('fs_edit_coupon_brief',dict(args,**change))
        self.approval['valid_until']=self.now.isoformat()
        with self.assertRaises(PermissionError):self.call('fs_edit_coupon_brief',args)
        self.approval=original;self.iam['bindings']['operator']['roles']=['Viewer'];self.policy_path.write_text(json.dumps(self.iam))
        with self.assertRaises(PermissionError):self.call('fs_edit_coupon_brief',args)
        self.assertEqual(self.posts,[])

    def test_unknown_same_original_id_only_reads_and_never_posts_again(self):
        args=self.grant();self.timeout=True
        result=self.call('fs_edit_coupon_brief',args)
        self.assertEqual(result['state'],'unknown');self.assertFalse(result['business_confirmed'])
        self.assertEqual(self.call('fs_edit_coupon_brief',args),result)
        after=self.call('fs_coupon_operation',dict(operation_id=args['operation_id'],reconcile=True))
        self.assertEqual(after['state'],'unknown');self.assertEqual(len(self.posts),1)
        with self.assertRaises(PermissionError):self.call('fs_coupon_operation',{'operation_id':'another-operation'})

    def test_disabled_unused_and_actual_before_hash_remain_required(self):
        for field in ('status','fetch_qty','used_qty'):
            self.row[field]=1;args=self.grant()
            with self.subTest(field=field),self.assertRaisesRegex(PermissionError,'native_coupon_not_disabled_unused'):
                self.call('fs_edit_coupon_brief',args)
            self.row[field]=0
        args=self.grant();self.row['brief']='Changed after approval'
        receipt=self.call('fs_edit_coupon_brief',args)
        self.assertEqual((receipt['state'],receipt['dispatch_state']),('rejected','not_started'))
        self.assertEqual(self.posts,[])

    def test_root_file_producer_binds_one_actual_run_and_preserves_expiry_and_IAM(self):
        import conversation_user_data as module
        producer=module.campaign_approval
        self.now=datetime.now(timezone.utc)
        args=self.grant();record=deepcopy(self.approval)
        path=Path(self.temp.name)/'backend/native-coupon-approval.json';path.parent.mkdir()
        real_lstat=Path.lstat;real_fstat=os.fstat;identity={'owner':0,'mode':0o600}
        def view(info,directory=False):
            values={k:getattr(info,k) for k in dir(info) if k.startswith('st_')}
            values.update(st_uid=0 if directory else identity['owner'],st_gid=0,
                          st_mode=(stat.S_IFDIR|0o755) if directory else stat.S_IFREG|identity['mode'])
            # Windows ChangeTime may refresh on opening a handle; model the
            # Linux ctime contract here, retaining the explicit FD drift case.
            if os.name=='nt':values['st_ctime_ns']=info.st_mtime_ns
            return SimpleNamespace(**values)
        def lstat(p,*a,**kw):
            info=real_lstat(p,*a,**kw)
            return view(info,directory=True) if p in path.parents else view(info) if p==path else info
        def fstat(fd):
            info=real_fstat(fd)
            if not path.exists():return info
            approval=real_lstat(path)
            if (info.st_dev,info.st_ino)!=(approval.st_dev,approval.st_ino):return info
            result=view(info)
            if identity.get('drift'):result.st_ctime_ns+=1
            return result
        # Only OS root/mode identities are fixtures; the file bytes/FD/inode,
        # binding, IAM, backend, durable ledger and final writer remain real.
        with patch.object(module,'CAMPAIGN_APPROVAL_FILE',path),patch.object(Path,'lstat',lstat),patch.object(os,'fstat',fstat):
            from campaign_backend.adapters import AdminRead
            factory=self.data.campaign.reader_factory
            state=self.backend.state_dir;state.mkdir(mode=0o700,parents=True)
            # Root approval identities must not replace the runner-owned
            # private ledger directory/FD metadata consumed by the real writer.
            self.assertEqual(Path.lstat(state),real_lstat(state))
            (state/'policy.json').write_text(json.dumps(fixture.policy()))
            with patch.dict(os.environ,{'CAMPAIGN_BACKEND_STATE_DIR':str(state)}),patch.object(AdminRead,'from_shared_session',side_effect=factory):
                self.data.campaign=module.NativeCouponActions.runtime(self.conversation.native,self.binding)
            self.assertIs(self.data.campaign.approval_source,producer)
            with self.assertRaisesRegex(PermissionError,'business_authorization_required'):self.call('fs_edit_coupon_brief',args)
            path.write_text(json.dumps(record))
            probe=state/'fixture-identity-check'
            with probe.open('xb') as stream:
                info=os.fstat(stream.fileno());actual=real_fstat(stream.fileno())
                self.assertEqual((info.st_uid,info.st_gid,info.st_mode),(actual.st_uid,actual.st_gid,actual.st_mode))
            probe.unlink()
            for key in self.binding:
                bad=deepcopy(record);bad['binding'][key]='wrong';path.write_text(json.dumps(bad))
                with self.subTest(key=key),self.assertRaisesRegex(PermissionError,'business_authorization_mismatch'):self.call('fs_edit_coupon_brief',args)
            path.write_text(json.dumps(record))
            for owner,mode in ((9876,0o600),(0,0o644)):
                identity.update(owner=owner,mode=mode)
                with self.assertRaisesRegex(PermissionError,'business_authorization_file_boundary'):self.call('fs_edit_coupon_brief',args)
            identity.update(owner=0,mode=0o600)
            identity['drift']=True
            with self.assertRaisesRegex(PermissionError,'business_authorization_file_changed'):self.call('fs_edit_coupon_brief',args)
            identity['drift']=False
            bad=deepcopy(record);bad['valid_until']=self.now.isoformat();path.write_text(json.dumps(bad))
            with self.assertRaisesRegex(PermissionError,'business_authorization_expired'):self.call('fs_edit_coupon_brief',args)
            path.write_text(json.dumps(record));saved=path.read_bytes()
            self.assertTrue(self.call('fs_edit_coupon_brief',args)['business_confirmed'])
            self.assertEqual(path.read_bytes(),saved);self.assertEqual(len(self.posts),1)
            self.iam['bindings']['operator']['roles']=['Viewer'];self.policy_path.write_text(json.dumps(self.iam))
            with self.assertRaisesRegex(PermissionError,'native_campaign_access_denied'):self.call('fs_coupon_operation',{'operation_id':args['operation_id']})

    def test_approval_expiring_during_detail_cannot_reach_mutation(self):
        args=self.grant();times=iter((self.now,self.now+timedelta(minutes=2)))
        self.data.campaign.clock=lambda:next(times)
        with self.assertRaisesRegex(PermissionError,'business_authorization_expired'):self.call('fs_edit_coupon_brief',args)
        self.assertEqual(self.posts,[])

    def test_worker_request_grants_scope_host_IAM_and_original_coupon_executor(self):
        import hashlib,io,re,secrets,threading,time,types
        from dataclasses import dataclass
        from urllib.error import HTTPError
        from urllib.request import Request,HTTPRedirectHandler
        from urllib.parse import urlsplit
        import conversation_native as native
        from native_chat import NativeChatScope
        source=HERE.parent/'source'
        core=source.parents[1]/'hermes-v2-core-20261020/source'
        channel=source.parents[2]/'fc-coins/fc-review-channel-20261026/source'
        def declarations(path,names,namespace):
            nodes=[n for n in ast.parse(path.read_text('utf-8')).body if getattr(n,'name',None) in names]
            self.assertEqual({n.name for n in nodes},set(names))
            exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),namespace)
            return namespace
        transport=declarations(core/'transport.py',('Grant','Grants','Proxy'),
            dict(dataclass=dataclass,deepcopy=deepcopy,hashlib=hashlib,secrets=secrets,threading=threading,time=time,json=json))
        proxy_module=types.ModuleType('proxy_gateway')
        declarations(channel/'proxy_gateway.py',('native_scope',),proxy_module.__dict__)
        scope=NativeChatScope(self.binding,lambda:self.conversation.native.authorized(self.binding),
            model_schemas=lambda:[],call_tool=lambda name,args:self.conversation.native.host_tool(self.binding,name,args))
        grants=transport['Grants']();token=grants.mint(self.binding['owner'],self.binding['turn_id'],self.binding['lease'])
        proxy=transport['Proxy'](grants,lambda grant:types.SimpleNamespace(scope=scope))
        sid=self.binding['session_id'];path=Path(self.temp.name)/'admissions'/(sid+'.json');path.parent.mkdir()
        item=dict(session_id=sid,model='deepseek-flash',prompt='',token=token,ready=True,conversation=True,run_id=self.binding['run_id'],
            native_chat=dict(binding=self.binding,key='hn-'+'a'*64,fingerprint='b'*64,environment=dict(
                profile=native.NATIVE_ROOT+'/profiles/'+native.sha(self.binding['owner'].encode()),workspace=native.execution_workspace(self.binding),files=[])))
        path.write_text(json.dumps(item));wire=[]
        def opening(*args):
            def request(req,**kwargs):
                self.assertEqual((req.get_method(),urlsplit(req.full_url).path),('POST','/fc/tools/call'))
                body=json.loads(req.data);wire.append(body['name'])
                with patch.dict(sys.modules,{'proxy_gateway':proxy_module}):
                    value=proxy.dispatch('POST','/fc/tools/call',req.get_header('Authorization')[7:],body)
                return io.BytesIO(json.dumps(value).encode())
            return types.SimpleNamespace(open=request)
        worker=declarations(channel/'hermes_worker.py',('admission','call_tool','NoRedirect'),
            dict(Path=Path,re=re,json=json,Request=Request,HTTPRedirectHandler=HTTPRedirectHandler,HTTPError=HTTPError,
                 build_opener=opening,ADMISSIONS=path.parent,MAX_PROVIDER_WIRE_BYTES=10*1024*1024,PROXY='http://127.0.0.1:8940'))
        worker['fixed']=self.binding
        # Execute the exact worker-native active callback and data_call lambda.
        create=next(n for n in ast.walk(ast.parse((channel/'hermes_worker.py').read_text('utf-8'))) if isinstance(n,ast.FunctionDef) and n.name=='_create_native_agent')
        active=next(n for n in create.body if isinstance(n,ast.FunctionDef) and n.name=='active')
        exec(compile(ast.Module(body=[active],type_ignores=[]),str(channel/'hermes_worker.py'),'exec'),worker)
        relay=next(n.value for n in create.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Attribute) and t.attr=='data_call' for t in n.targets))
        backend=native.NativeDockerBackend.__new__(native.NativeDockerBackend)
        backend.binding=self.binding;backend.authorize=worker['active']
        backend.data_call=eval(compile(ast.Expression(body=relay),str(channel/'hermes_worker.py'),'eval'),worker)
        plugin_path=source.parents[1]/'hermes-server-unify-20261022/fs_readonly/__init__.py'
        spec=importlib.util.spec_from_file_location('native_coupon_plugin',plugin_path,submodule_search_locations=[str(plugin_path.parent)])
        plugin=importlib.util.module_from_spec(spec);spec.loader.exec_module(plugin)
        registered={}
        class Registry:
            def get_entry(self,*args,**kwargs):return None
            def register(self,**tool):registered[tool['name']]=tool
        plugin.register_scope(Registry(),'synthetic-owner-profile')
        def call(name,args):
            context=native._NATIVE_BACKEND.set(backend)
            try:return json.loads(registered[name]['handler'](args,task_id=self.binding['turn_id']))
            finally:native._NATIVE_BACKEND.reset(context)
        self.assertIn('fs_edit_coupon_brief',registered)
        self.assertEqual(call('fs_coupon_candidates',{'page':1,'limit':1})['items'][0]['native_id'],'123')
        args=self.grant();self.assertTrue(call('fs_edit_coupon_brief',args)['business_confirmed'])
        self.assertTrue(call('fs_coupon_operation',{'operation_id':args['operation_id']})['business_confirmed'])
        self.assertEqual(len(self.posts),1);self.assertIn('fs.native.user_data',wire)
        # Same real worker Request -> Grants/Proxy -> scope -> host -> IAM ->
        # backend/SQLite; only the final Admin endpoint is synthetic.
        grant_args=self.issuance();receipt=call('fs_grant_coupon',grant_args)
        self.assertTrue(receipt['business_confirmed'])
        self.assertEqual(call('fs_grant_coupon',grant_args),receipt)
        self.assertEqual(len(self.posts),2);self.assertNotIn('one@example.test',json.dumps(receipt))
        with self.assertRaises(PermissionError):
            worker['call_tool']('fs.native.user_data',dict(binding=dict(self.binding,lease='d'*32),name='fs_coupon_detail',arguments={'native_id':'123'}),session_id=sid)
        with patch.dict(sys.modules,{'proxy_gateway':proxy_module}),self.assertRaises(PermissionError):
            proxy.dispatch('POST','/fc/tools/call',grants.mint('other',self.binding['turn_id'],self.binding['lease']),dict(name='fs.native.check',arguments={'binding':self.binding}))
        path.write_text(json.dumps(dict(item,ready=False)))
        with self.assertRaises(PermissionError):call('fs_coupon_detail',{'native_id':'123'})
        self.assertEqual(len(self.posts),2)
