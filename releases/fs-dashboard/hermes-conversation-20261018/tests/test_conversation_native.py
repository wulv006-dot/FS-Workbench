"""Native chat file bridge uses the real conversation SQLite and raw files."""
import hashlib
import importlib.util
import json
import threading
import types
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
from conversation_store import ConversationStore
from conversation_files import ConversationFiles


class NativeWorkspaceTests(unittest.TestCase):
    def test_two_sheet_real_xlsx_bytes_versions_and_natural_followup(self):
        import io
        from openpyxl import Workbook,load_workbook
        from conversation_native import NativeWorkspace
        with tempfile.TemporaryDirectory() as root:
            store=ConversationStore(Path(root)/'store');cid=store.create('alice')['conversation_id']
            files=ConversationFiles(store);bridge=NativeWorkspace(store,Path(root)/'native')
            book=Workbook();book.active.title='data';book.active.append(['a','b']);book.active.append([10,25])
            book.create_sheet('notes')['A1']='Keep this sheet unchanged.'
            stream=io.BytesIO();book.save(stream);book.close();original_bytes=stream.getvalue()
            original=files.save('alice',cid,'book (1).xlsx',original_bytes,'native_xlsx_original')
            env=bridge.prepare('alice',cid,[original['file_id']]);path=Path(env['workspace'])/env['files'][0]['path']
            previous=original
            for index,value in enumerate((30,35)):
                changed=load_workbook(path);changed['data']['B2']=value;changed.save(path);changed.close()
                cards=bridge.collect('alice',cid,'run_'+str(index+1)*32)
                self.assertEqual(len(cards),1);current=cards[0]
                self.assertEqual(current['parent_id'],previous['file_id']);self.assertEqual(current['version'],index+2)
                downloaded=files.read('alice',cid,current['file_id'])['content']
                self.assertEqual(hashlib.sha256(downloaded).hexdigest(),current['sha256'])
                parsed=load_workbook(io.BytesIO(downloaded));self.assertEqual(parsed.sheetnames,['data','notes'])
                self.assertEqual(list(parsed['data'].values),[('a','b'),(10,value)])
                self.assertEqual(parsed['notes']['A1'].value,'Keep this sheet unchanged.');parsed.close()
                previous=current
                # Nothing is configured as a material task. The current cid's
                # workspace and immutable generated version survive a new turn.
                again=bridge.prepare('alice',cid)
                self.assertIn(current['file_id'],[item['file_id'] for item in again['files']])
            self.assertEqual(files.read('alice',cid,original['file_id'])['content'],original_bytes)

    def test_same_owner_profile_shared_but_workspaces_and_other_owner_isolated(self):
        from conversation_native import NativeWorkspace
        with tempfile.TemporaryDirectory() as root:
            store=ConversationStore(Path(root)/'store')
            alice=store.create('alice')['conversation_id']; second=store.create('alice')['conversation_id']
            bob=store.create('bob')['conversation_id']
            bridge=NativeWorkspace(store,Path(root)/'native')
            a=bridge.prepare('alice',alice); a2=bridge.prepare('alice',second); b=bridge.prepare('bob',bob)
            self.assertEqual(a['profile'],a2['profile']);self.assertNotEqual(a['profile'],b['profile'])
            self.assertNotEqual(a['workspace'],a2['workspace'])
            with self.assertRaises(LookupError):bridge.prepare('bob',alice)

    def test_real_upload_history_mutation_export_and_download_parent(self):
        from conversation_native import NativeWorkspace
        with tempfile.TemporaryDirectory() as root:
            store=ConversationStore(Path(root)/'store'); cid=store.create('alice')['conversation_id']
            files=ConversationFiles(store); original=files.save('alice',cid,'data.csv',b'x\n1\n','input_native_1')
            bridge=NativeWorkspace(store,Path(root)/'native')
            state=bridge.prepare('alice',cid,[original['file_id']])
            path=Path(state['workspace'])/state['files'][0]['path']
            self.assertEqual(path.read_bytes(),b'x\n1\n')
            again=bridge.prepare('alice',cid,[])
            self.assertEqual(again['files'],state['files'])
            path.write_bytes(b'x\n2\n')
            cards=bridge.collect('alice',cid,'run_'+'a'*32)
            self.assertEqual(len(cards),1);self.assertEqual(cards[0]['parent_id'],original['file_id'])
            self.assertEqual(files.read('alice',cid,cards[0]['file_id'])['content'],b'x\n2\n')
            self.assertEqual(files.read('alice',cid,original['file_id'])['content'],b'x\n1\n')
            self.assertEqual(bridge.collect('alice',cid,'run_'+'a'*32),cards)
            chosen=bridge.prepare('alice',cid,[original['file_id']])
            old=next(item for item in chosen['files'] if item['file_id']==original['file_id'])
            self.assertEqual((Path(chosen['workspace'])/old['path']).read_bytes(),b'x\n1\n')
            self.assertEqual(path.read_bytes(),b'x\n2\n')
            derived=bridge.prepare('alice',cid,[cards[0]['file_id']])
            self.assertEqual(len([item for item in derived['files'] if item['file_id']==cards[0]['file_id']]),1)
            generated=Path(state['workspace'])/'answer.txt';generated.write_bytes(b'answer')
            more=bridge.collect('alice',cid,'run_'+'b'*32)
            self.assertEqual(len(more),1);self.assertEqual(more[0]['filename'],'answer.txt')

    def test_export_rejects_symlink_and_does_not_read_other_directory(self):
        from conversation_native import NativeWorkspace
        with tempfile.TemporaryDirectory() as root:
            store=ConversationStore(Path(root)/'store');cid=store.create('alice')['conversation_id']
            bridge=NativeWorkspace(store,Path(root)/'native');state=bridge.prepare('alice',cid)
            outside=Path(root)/'private.txt';outside.write_bytes(b'PRIVATE_SENTINEL')
            with patch('conversation_native.os.walk',return_value=iter([(state['workspace'],[],['escape'])])), patch.object(Path,'is_symlink',return_value=True):
                with self.assertRaises(ValueError):bridge.collect('alice',cid,'run_'+'a'*32)



class NativeFilesTests(unittest.TestCase):
    def test_upload_preserves_general_file_bytes_without_table_parse(self):
        with tempfile.TemporaryDirectory() as root:
            store = ConversationStore(root)
            cid = store.create('alice')['conversation_id']
            files = ConversationFiles(store)
            for n, (name, raw) in enumerate((('notes (1).txt', b'hello\r\nworld'),
                    ('picture.png', b'\x89PNG\x00synthetic'), ('report.pdf', b'%PDF-synthetic'),
                    ('book.xlsx', b'not-yet-parsed-workbook'), ('data.csv', b'\xff\x00raw'))):
                with self.subTest(filename=name), patch('conversation_files.parse_table', side_effect=AssertionError('upload must not parse')):
                    item = files.save('alice', cid, name, raw, 'upload_native_'+str(n))
                    self.assertEqual(files.read('alice', cid, item['file_id'])['content'], raw)
                    self.assertEqual(item['sha256'], hashlib.sha256(raw).hexdigest())
                    self.assertEqual(files.describe('alice', cid, item['file_id'])['status'], 'available')
                    with self.assertRaises(LookupError):
                        files.read('bob', cid, item['file_id'])

    def test_general_output_immutable_download_and_request_conflict(self):
        with tempfile.TemporaryDirectory() as root:
            store = ConversationStore(root)
            cid = store.create('alice')['conversation_id']
            files = ConversationFiles(store)
            item = files.save('alice', cid, 'analysis.json', b'{"total":15}', 'output_native_1', generated=True)
            self.assertTrue(item['generated'])
            self.assertEqual(files.lookup('alice', cid, 'output_native_1')['file_id'], item['file_id'])
            with self.assertRaises(ValueError):
                files.save('alice', cid, 'analysis.json', b'{"total":16}', 'output_native_1', generated=True)
            self.assertEqual(files.read('alice', cid, item['file_id'])['content'], b'{"total":15}')



class NativeDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        @contextmanager
        def guard(_):
            yield True
        controller=types.ModuleType('controller');controller.NoRedirect=object;controller.admission_guard=guard
        controller.atomic=lambda path,value,**kw: cls.admissions.append(json.loads(json.dumps(value)))
        evidence=types.ModuleType('fs_evidence');evidence.build_book=lambda *a,**k: (_ for _ in ()).throw(AssertionError('native must not build FC book'))
        inprocess=types.ModuleType('fs_inprocess');inprocess.gateway=lambda *a,**k: (_ for _ in ()).throw(AssertionError('FC gateway'))
        inprocess.spending_hold=lambda *a,**kw:False;inprocess.active_model_tasks=lambda tasks:[]
        inprocess.native_gateway=lambda daily,scope,**kw:types.SimpleNamespace(scope=scope)
        pilot=types.ModuleType('pilot');pilot.encoded=json.dumps;pilot.digest=lambda value:hashlib.sha256(json.dumps(value).encode()).hexdigest();pilot.SHANGHAI=None
        cls.modules={'controller':controller,'fs_evidence':evidence,'fs_inprocess':inprocess,'pilot':pilot}
        core=SOURCE.parents[1]/'hermes-v2-core-20261020/source'
        sys.path.insert(0,str(core))
        path=SOURCE.parents[2]/'fc-coins/fc-pricing-v3-20261026/source/conversation_service.py'
        with patch.dict(sys.modules,cls.modules):
            spec=importlib.util.spec_from_file_location('native_active_service',path)
            cls.active=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.active)

    def fixture(self,root,real_tasks=None):
        self.__class__.admissions=[]
        class Grants:
            def mint(self,*a,**k):return 's'*43
            def revoke(self,*a):pass
        tasks=real_tasks or types.SimpleNamespace(create=lambda *a: (_ for _ in ()).throw(AssertionError('FC task created')))
        h=types.SimpleNamespace(root=Path(root)/'host',authorizer=lambda u:u=='alice',tasks=tasks,daily=None,
            grants=Grants(),lock=threading.RLock(),tokens={},books={},gateways={})
        service=self.active.ConversationService(h,Path(root)/'store',Path(root)/'run',pricing_only=False)
        service.pool.shutdown(wait=True);service.pricing_pool.shutdown(wait=True)
        if service.pricing is not None:service.pricing.pool.shutdown(wait=True)
        if real_tasks is None:service.hermes.tasks.db=service.store.db
        service.pool=types.SimpleNamespace(submit=lambda *a:None)
        service._monitor=lambda *a:None
        cid=service.store.create('alice')['conversation_id']
        return service,cid

    def test_real_taskstore_host_hook_is_readonly_and_stop_blocks_late_publication(self):
        path=SOURCE.parents[1]/'hermes-fc-pilot-20261013/pilot.py'
        spec=importlib.util.spec_from_file_location('native_real_pilot',path)
        pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot)
        with tempfile.TemporaryDirectory() as root,patch.dict(sys.modules,self.modules):
            tasks=pilot.TaskStore(Path(root)/'tasks.sqlite3')
            before=Path(tasks.path).read_bytes()
            service,cid=self.fixture(root,tasks)
            turn=service.submit('alice',cid,'hello','native_liveness_01')
            with service.store.db() as db:session=service.store._owned(db,'alice',cid)['session_id']
            run='run_'+'a'*32;service._request=lambda *a,**kw:(202,{'run_id':run})
            service._dispatch('alice',cid,turn['turn_id'],session,'hello','native_liveness_01')
            original=service.store.path.read_bytes()
            self.assertEqual(tasks._native_active_model_tasks(),{('alice',turn['turn_id'])})
            self.assertEqual(service.store.path.read_bytes(),original)
            service.native.append_event('alice',cid,turn['turn_id'],run,0,{'event':'message.delta','delta':'accepted before stop'})
            service.native.fence('alice',cid,turn['turn_id'])
            self.assertEqual(tasks._native_active_model_tasks(),set())
            self.assertIsNone(service.native.append_event('alice',cid,turn['turn_id'],run,1,{'event':'run.completed','output':'LATE_SENTINEL'}))
            environment=service.native.workspace.prepare('alice',cid)
            (Path(environment['workspace'])/'late.txt').write_bytes(b'LATE_SENTINEL')
            self.assertEqual(service.native.complete('alice',cid,turn['turn_id'],run),[])
            detail=service.store.detail('alice',cid)['turns'][0]
            self.assertEqual(detail['reply'],'accepted before stop');self.assertEqual(detail['files']['generated'],[])
            self.assertEqual(Path(tasks.path).read_bytes(),before)

    def test_plain_turn_raw_input_single_runs_post_and_trusted_schema_relay(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(sys.modules,self.modules):
            service,cid=self.fixture(root); calls=[]
            raw='  Read this file as requested.\nKeep my original wording.  '
            file=ConversationFiles(service.store).save('alice',cid,'notes.txt',b'original bytes','native_file_01')
            turn=service.submit('alice',cid,raw,'native_request_01',[file['file_id']])
            row=service.store.detail('alice',cid)['turns'][0]
            with service.store.db() as db:session=service.store._owned(db,'alice',cid)['session_id']
            service._request=lambda *a,**kw:(calls.append((a,kw)) or (202,{'run_id':'run_'+'a'*32}))
            service._dispatch('alice',cid,turn['turn_id'],session,raw,'native_request_01')
            self.assertEqual(len(calls),1);self.assertEqual(calls[0][0][:2],('POST','/v1/runs'))
            self.assertEqual(calls[0][0][2],{'input':raw,'session_id':session})
            self.assertNotIn('materials',self.admissions[-1]);self.assertIn('native_chat',self.admissions[-1])
            scope=service.hermes.gateways[turn['turn_id']].scope
            with self.assertRaises(PermissionError):scope.schemas()
            binding=scope.context('alice',turn['turn_id'],service.store.task_binding('alice',cid,turn['turn_id'])[1])
            schemas=[{'type':'function','function':{'name':'tool_search','parameters':{'type':'object','properties':{}}}}]
            value={'binding':binding,'model_schemas':schemas,'catalog_sha256':'f'*64,'registry_generation':7}
            self.assertTrue(scope.call('alice',binding['turn_id'],binding['lease'],'fs.native.register_schemas',value)['registered'])
            self.assertEqual(scope.schemas(),schemas)
            changed=json.loads(json.dumps(value));changed['model_schemas'][0]['function']['name']='anything_else'
            with self.assertRaises(PermissionError):scope.call('alice',binding['turn_id'],binding['lease'],'fs.native.register_schemas',changed)
            service.native.fence('alice',cid,turn['turn_id'])
            with self.assertRaises(PermissionError):scope.schemas()

    def test_lost_202_never_reposts_original_request(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(sys.modules,self.modules):
            service,cid=self.fixture(root);calls=[]
            turn=service.submit('alice',cid,'hello','native_unknown_01')
            with service.store.db() as db:session=service.store._owned(db,'alice',cid)['session_id']
            def request(*a,**kw):calls.append(a);raise OSError('synthetic lost 202')
            service._request=request
            try:service._dispatch('alice',cid,turn['turn_id'],session,'hello','native_unknown_01')
            except OSError:pass
            self.assertEqual(len(calls),1)
            self.assertEqual(service.store.detail('alice',cid)['turns'][0]['state'],'dispatch_unknown')
            # A second host call only consults the original persisted reservation.
            service._dispatch('alice',cid,turn['turn_id'],session,'hello','native_unknown_01')
            self.assertEqual(len(calls),1)
            original=service.native.row('alice',cid,turn['turn_id'])
            recovered=[]
            service._recover=lambda *args:recovered.append(args)
            service._request=lambda *args,**kw:(calls.append(args) or (200,{'status':'failed','run_id':'run_'+'a'*32,'session_id':session,'owner_alive':True}))
            service.native.reconcile_unknown('alice',cid,turn['turn_id'])
            self.assertEqual(calls[-1],('GET','/v1/native/'+session))
            self.assertEqual(len([v for v in calls if v[0]=='POST']),1)
            updated=service.native.row('alice',cid,turn['turn_id'])
            self.assertEqual(updated['fingerprint'],original['fingerprint'])
            self.assertEqual(updated['idempotency_key'],original['idempotency_key'])
            self.assertEqual(updated['binding']['lease'],original['binding']['lease'])
            self.assertEqual(recovered,[('alice',cid,turn['turn_id'],'run_'+'a'*32)])

class NativeDockerPolicyTests(unittest.TestCase):
    def test_native_contexts_restore_on_error_cancel_and_concurrent_owners(self):
        import asyncio
        from contextvars import ContextVar
        import conversation_native as native
        variables={key:ContextVar('test_'+key,default=None) for key in ('home','terminal','cwd','secret','multiplex')}
        constants=types.ModuleType('hermes_constants')
        constants.set_hermes_home_override=variables['home'].set;constants.reset_hermes_home_override=variables['home'].reset
        terminal=types.ModuleType('tools.terminal_scope')
        terminal.set_terminal_scope=variables['terminal'].set;terminal.reset_terminal_scope=variables['terminal'].reset
        cwd=types.ModuleType('agent.runtime_cwd')
        cwd.set_session_cwd=variables['cwd'].set;cwd.reset_session_cwd=variables['cwd'].reset
        secrets=types.ModuleType('agent.secret_scope')
        secrets.build_profile_secret_scope=lambda profile:{}
        secrets.set_secret_scope=lambda value,**kw:variables['secret'].set(kw['profile_home'])
        secrets.reset_secret_scope=variables['secret'].reset
        secrets.set_multiplex_context=variables['multiplex'].set;secrets.reset_multiplex_context=variables['multiplex'].reset
        def backend(owner,cid):
            bound=dict(owner=owner,conversation_id=cid,turn_id='c'*32,request_id='native_scope_01',session_id='hc_'+'d'*64,lease='e'*32,run_id='run_'+'f'*32)
            environment=dict(profile=native.NATIVE_ROOT+'/profiles/'+hashlib.sha256(owner.encode()).hexdigest(),workspace=native.NATIVE_ROOT+'/workspaces/'+cid,files=[])
            item=dict(session_id=bound['session_id'],run_id=bound['run_id'],ready=True,native_chat=dict(binding=bound,environment=environment,key='hn-'+'a'*64,fingerprint='b'*64))
            instance=object.__new__(native.NativeDockerBackend)
            instance.binding=bound;instance.item=item;instance.profile=Path(environment['profile']);instance.workspace=Path(environment['workspace']);instance.policy=native.docker_policy(bound);instance.authorize=lambda:True
            return instance
        modules={'hermes_constants':constants,'tools.terminal_scope':terminal,'agent.runtime_cwd':cwd,'agent.secret_scope':secrets}
        barrier=threading.Barrier(4);results=[];errors=[]
        def run(owner,cid):
            try:
                instance=backend(owner,cid)
                with instance.scope():
                    barrier.wait(timeout=5)
                    results.append((owner,cid,variables['home'].get(),variables['cwd'].get(),native.current_native_backend() is instance))
                    self.assertEqual(variables['secret'].get(),str(instance.profile));self.assertIs(variables['multiplex'].get(),True)
                self.assertTrue(all(v.get() is None for v in variables.values()))
                for failure in (ValueError('synthetic'),asyncio.CancelledError()):
                    with self.assertRaises(type(failure)):
                        with instance.scope():raise failure
                    self.assertTrue(all(v.get() is None for v in variables.values()))
                    self.assertIsNone(native.current_native_backend())
            except BaseException as error:errors.append(error)
        with patch.dict(sys.modules,modules):
            threads=[threading.Thread(target=run,args=value) for value in (('alice','1'*32),('alice','2'*32),('bob','3'*32))]
            for thread in threads:thread.start()
            barrier.wait(timeout=5)
            self.assertTrue(all(v.get() is None for v in variables.values()))
            for thread in threads:thread.join(timeout=5)
        self.assertFalse(errors,errors);self.assertEqual(len(results),3)
        alice={v[2] for v in results if v[0]=='alice'};bob={v[2] for v in results if v[0]=='bob'}
        self.assertEqual(len(alice),1);self.assertTrue(alice.isdisjoint(bob))
        self.assertEqual(len({v[3] for v in results}),3);self.assertTrue(all(v[4] for v in results))

    def test_only_automatic_mount_discovery_uses_empty_home_not_configuration(self):
        import asyncio
        from conversation_native import install_native_backend_guards, _NATIVE_BACKEND
        observed=[]
        model=types.ModuleType('model_tools');model.handle_function_call=lambda *a,**k:'legacy'
        docker=types.ModuleType('tools.environments.docker')
        home=['owner']
        failure=[None]
        def mount_args():
            observed.append(('mount',home[0]))
            if failure[0] is not None:raise failure[0]
            return []
        docker._readonly_skill_mount_args=mount_args
        class Environment:
            def __init__(self):
                observed.append(('config',home[0]))
                if home[0]!='owner':raise PermissionError('readonly_config_initialization')
                docker._readonly_skill_mount_args()
            def _run_command(self,*args):return []
        docker.DockerEnvironment=Environment
        @contextmanager
        def empty():
            previous=home[0];home[0]='empty_readonly'
            try:yield
            finally:home[0]=previous
        backend=types.SimpleNamespace(check=lambda *a:None,empty_backend_home=empty)
        package=types.ModuleType('tools.environments');package.docker=docker
        inline=types.ModuleType('agent.inline_tool_executors');inline.INLINE_TOOL_EXECUTORS={}
        with patch.dict(sys.modules,{'model_tools':model,'tools.environments':package,'tools.environments.docker':docker,'agent.inline_tool_executors':inline}):
            install_native_backend_guards();install_native_backend_guards()
            token=_NATIVE_BACKEND.set(backend)
            try:Environment()
            finally:_NATIVE_BACKEND.reset(token)
            Environment()
            self.assertEqual(observed,[('config','owner'),('mount','empty_readonly'),('config','owner'),('mount','owner')])
            for error in (ValueError('synthetic'),asyncio.CancelledError()):
                failure[0]=error;token=_NATIVE_BACKEND.set(backend)
                try:
                    with self.assertRaises(type(error)):Environment()
                    self.assertEqual(home[0],'owner')
                finally:_NATIVE_BACKEND.reset(token)

    def test_inline_memory_stop_and_missing_approval_cannot_bypass_registry_guard(self):
        from conversation_native import install_native_backend_guards,_NATIVE_BACKEND
        calls=[];active=[True];approval=[True]
        session='hc_'+'a'*64
        def check(task=None):
            if not active[0] or task not in (None,session):raise PermissionError('inactive')
        backend=types.SimpleNamespace(check=check,binding={'session_id':session},policy={'TERMINAL_ENV':'docker'})
        model=types.ModuleType('model_tools');model.handle_function_call=lambda *a,**k:calls.append('registry')
        docker=types.ModuleType('tools.environments.docker')
        docker.DockerEnvironment=type('Environment',(),{'__init__':lambda self:None,'_run_command':lambda *a:[]})
        docker._readonly_skill_mount_args=lambda:[]
        package=types.ModuleType('tools.environments');package.docker=docker
        inline=types.ModuleType('agent.inline_tool_executors');inline.INLINE_TOOL_EXECUTORS={'memory':lambda *args:calls.append('inline')}
        wa=types.ModuleType('tools.write_approval');wa.write_approval_enabled=lambda _:approval[0]
        terminal=types.ModuleType('tools.terminal_scope');terminal.get_terminal_scope=lambda:backend.policy
        with patch.dict(sys.modules,{'model_tools':model,'tools.environments':package,'tools.environments.docker':docker,'agent.inline_tool_executors':inline,'tools.write_approval':wa,'tools.terminal_scope':terminal}):
            install_native_backend_guards();install_native_backend_guards()
            token=_NATIVE_BACKEND.set(backend)
            try:
                inline.INLINE_TOOL_EXECUTORS['memory'](None,{},types.SimpleNamespace(effective_task_id=session))
                active[0]=False
                with self.assertRaises(PermissionError):inline.INLINE_TOOL_EXECUTORS['memory'](None,{},types.SimpleNamespace(effective_task_id=session))
                active[0]=True;approval[0]=False
                with self.assertRaises(PermissionError):inline.INLINE_TOOL_EXECUTORS['memory'](None,{},types.SimpleNamespace(effective_task_id=session))
                with self.assertRaises(PermissionError):model.handle_function_call('skill_manage',{},task_id=session)
            finally:_NATIVE_BACKEND.reset(token)
            inline.INLINE_TOOL_EXECUTORS['memory'](None,{},None)
        self.assertEqual(calls,['inline','inline'])

    def test_only_cid_workspace_bind_no_parent_mount_or_environment(self):
        from conversation_native import docker_policy, validate_docker_command
        binding={'owner':'alice','conversation_id':'a'*32,'turn_id':'b'*32,'request_id':'req_12345678','session_id':'hc_'+'c'*64,'lease':'d'*32,'run_id':'run_'+'e'*32}
        root='/var/lib/fs-hermes-fc/native'
        policy=docker_policy(binding,root)
        workspace=root+'/workspaces/'+'a'*32
        self.assertEqual(policy['TERMINAL_ENV'],'docker')
        self.assertEqual(policy['TERMINAL_DOCKER_FORWARD_ENV'],'[]')
        image='sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544'
        command=['/opt/fs-native-bin/docker','run','-d','--network=none','--cap-drop=ALL','--security-opt=no-new-privileges','-v',workspace+':/workspace',image,'sleep','infinity']
        validate_docker_command(command,workspace,image)
        for extra in (['-v','/profile:/profile:ro'],['-v','/var/run/docker.sock:/var/run/docker.sock'],['-e','FAKE_TOKEN=PRIVATE_SENTINEL'],['--privileged']):
            changed=command[:-3]+extra+command[-3:]
            with self.subTest(extra=extra),self.assertRaises((ValueError,PermissionError)):
                validate_docker_command(changed,workspace,image)
        with self.assertRaises((ValueError,PermissionError)):
            validate_docker_command([x.replace('--network=none','--network=host') for x in command],workspace,image)

    def test_profile_configuration_enables_pending_tools_and_owner_namespace(self):
        from conversation_native import NativeWorkspace, native_profile_config
        config=native_profile_config()
        self.assertIs(config['memory']['write_approval'],True)
        self.assertIs(config['skills']['write_approval'],True)
        self.assertIs(config['memory']['memory_enabled'],True)
        self.assertIs(config['memory']['user_profile_enabled'],True)
        self.assertEqual(config['model']['context_length'],1048576)
        self.assertNotIn('skip_memory',config)


class NativeResolverTests(unittest.TestCase):
    def test_official_original_key_lookup_is_readonly_bounded_and_never_not_found(self):
        from conversation_native import readonly_native_run
        import sqlite3
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'official.db'
            db=sqlite3.connect(path)
            db.execute('CREATE TABLE run_idempotency(scope TEXT,idempotency_key TEXT,fingerprint TEXT,run_id TEXT,status_json TEXT,owner_pid INTEGER,owner_started INTEGER,updated_at REAL)')
            session='hc_'+'a'*64;run='run_'+'b'*32
            db.execute('INSERT INTO run_idempotency VALUES(?,?,?,?,?,?,?,?)',('scope','key','c'*64,run,json.dumps({'session_id':session,'status':'queued','output':'PRIVATE_SENTINEL'}),123,9,1000))
            db.commit();db.close();before=path.read_bytes()
            result=readonly_native_run(path,scope='scope',key='key',fingerprint='c'*64,session_id=session,owner_alive=lambda *a:True,now=1001)
            self.assertEqual(result['run_id'],run);self.assertEqual(result['status'],'queued')
            self.assertNotIn('PRIVATE_SENTINEL',str(result));self.assertEqual(path.read_bytes(),before)
            missing=readonly_native_run(path,scope='scope',key='missing',fingerprint='c'*64,session_id=session,owner_alive=lambda *a:True,now=1001)
            self.assertEqual(missing,{'status':'unknown','run_id':None})
            with self.assertRaises(PermissionError):readonly_native_run(path,scope='scope',key='key',fingerprint='d'*64,session_id=session,owner_alive=lambda *a:True,now=1001)
            stale=readonly_native_run(path,scope='scope',key='key',fingerprint='c'*64,session_id=session,owner_alive=lambda *a:False,now=1001)
            self.assertEqual(stale['status'],'unknown')
            expired=readonly_native_run(path,scope='scope',key='key',fingerprint='c'*64,session_id=session,owner_alive=lambda *a:True,now=1000+86401)
            self.assertEqual(expired['status'],'unknown')


if __name__ == '__main__':
    unittest.main()
