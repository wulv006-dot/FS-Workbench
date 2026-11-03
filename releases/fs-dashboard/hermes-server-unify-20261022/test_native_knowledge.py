import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'releases/fs-dashboard/knowledge-layering-20261023/source'),
              str(ROOT/'releases/fs-dashboard/cache-archive-retention-20261025/source'),
              str(ROOT/'releases/fs-dashboard/user-analytics-20261022/source'),
              str(ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013')]
from fs_readonly.knowledge import NativeKnowledge, register


class Native(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.adapter=NativeKnowledge(self.root)
        self.info=dict(session_id='FS-new-1',platform='desktop',profile_name='fixture')
        self.row=dict(id='fc.rule',revision='v2',layer='current',status='effective',modules=['FC27'],
                      effective_at='2026-10-22',owner='fixture',authority='git',supersedes=['fc.rule@v1'],
                      provenance=['offline_fixture'],source=dict(path='rule.md',sha256=hashlib.sha256(b'current rule').hexdigest()))
        self.folder=self.root/'knowledge-releases/fixed';self.folder.mkdir(parents=True)
        (self.folder/'rule.md').write_bytes(b'current rule')
        self.index=dict(contract='fs-knowledge-index-v1',release='offline-fixed',release_state='published',
                        source_commit='a'*40,source_root='knowledge-releases/fixed',entries=[self.row])
        self.route=dict(platform='desktop',profile_name='fixture',catalog='knowledge-releases/fixed/index.json',
                        modules=['FC27'],sha256='')
        self.policy=dict(contract='fs-knowledge-load-policy-v1',requests={},native=dict(enabled=True,routes=[self.route],readonly_sessions={}))
        self.save_index();self.save_policy()
        toolsets=types.ModuleType('toolsets');toolsets.TOOLSET_SESSION_PLATFORMS={}
        self.patcher=patch.dict(sys.modules,{'toolsets':toolsets});self.patcher.start();self.addCleanup(self.patcher.stop)

    def prompt(self, info):
        self.adapter.pin(info)
        return self.adapter.prompt(info)

    def save_index(self):
        raw=json.dumps(self.index).encode();(self.folder/'index.json').write_bytes(raw)
        self.route['sha256']=hashlib.sha256(raw).hexdigest()

    def save_policy(self):
        (self.root/'knowledge-load-policy.json').write_bytes(json.dumps(self.policy).encode())

    def read(self,**args):
        return self.adapter.call('fs_read_knowledge',dict(modules=['FC27'],**args),session_id=self.info['session_id'],task_id='original-task-1')

    def test_new_session_short_index_and_on_demand_hashed_content(self):
        prompt=self.prompt(self.info)
        self.assertIn('fc.rule',prompt);self.assertNotIn('current rule',prompt)
        self.assertLess(len(prompt),12000)
        selected=self.read(entry_ids=['fc.rule'])
        self.assertEqual(selected['entries'][0]['content'],'current rule')
        self.assertEqual(selected['entries'][0]['content_sha256'],hashlib.sha256(b'current rule').hexdigest())

    def test_same_session_and_request_remain_pinned_after_publication_change(self):
        first=self.prompt(self.info);selected=self.read()
        self.index['release']='later';self.row['revision']='v3';self.save_index();self.save_policy()
        self.assertEqual(self.prompt(self.info),first)
        self.assertEqual(self.read(),selected)
        next_info=dict(self.info,session_id='FS-new-2')
        self.assertIn('later',self.prompt(next_info))
        with self.assertRaisesRegex(ValueError,'catalog_changed'):
            self.adapter.call('fs_read_knowledge',{'modules':['FC27']},session_id=self.info['session_id'],task_id='other-original-task')

    def test_old_unpinned_session_does_not_silently_adopt_new_rule(self):
        with self.assertRaises(FileNotFoundError):self.read()

    def test_other_platform_profile_and_disabled_routes_are_untouched(self):
        for info in [dict(self.info,platform='feishu'),dict(self.info,profile_name='other')]:
            self.assertEqual(self.prompt(info),'')
            self.assertIsNone(self.adapter.guard('terminal',{},session_id=info['session_id'],task_id='normal'))
        self.policy['native']['enabled']=False;self.save_policy()
        self.assertEqual(self.prompt(self.info),'')

    def test_candidate_conflict_and_other_module_not_misused(self):
        self.index['entries'].append(dict(self.row,revision='idea',layer='candidate',status='pending'))
        self.save_index();self.save_policy();self.prompt(self.info)
        self.assertEqual(self.read()['entries'][0]['revision'],'v2')
        self.assertEqual(self.read(entry_ids=['not.formal'])['status'],'missing_or_out_of_scope')
        with self.assertRaisesRegex(ValueError,'module_scope'):
            self.adapter.call('fs_read_knowledge',{'modules':['D4']},session_id=self.info['session_id'],task_id='same-task')

    def test_explicit_history_and_date_are_not_current_rule(self):
        (self.folder/'old.md').write_bytes(b'why the old decision')
        old=dict(self.row,revision='v1',layer='archive',status='archived',effective_at='2026-10-21',
                 source=dict(path='old.md',sha256=hashlib.sha256(b'why the old decision').hexdigest()))
        self.index['entries'].append(old);self.save_index();self.save_policy();self.prompt(self.info)
        self.assertEqual(self.read()['entries'][0]['revision'],'v2')
        v=self.read(entry_ids=['fc.rule'],revision='v1',history=True)
        self.assertTrue(v['history']);self.assertEqual(v['entries'][0]['effective_at'],'2026-10-21')
        with self.assertRaisesRegex(ValueError,'explicit_history'):self.read(revision='v1')

    def test_default_index_hides_retired_metadata_and_explicit_history_preserves_it(self):
        self.index['entries'].append(dict(self.row,revision='v1',layer='archive',status='retired'))
        self.index['entries'].append(dict(self.row,id='fc.idea',revision='draft',layer='candidate',status='pending'))
        self.save_index();self.save_policy();self.prompt(self.info)
        kwargs=dict(session_id=self.info['session_id'],task_id='original-task-1')
        current=self.adapter.call('fs_get_knowledge_index',{},**kwargs)
        self.assertEqual([(r['id'],r['revision']) for r in current['entries']],[('fc.rule','v2')])
        self.assertFalse(current['history']);self.assertTrue(current['history_available'])
        history=self.adapter.call('fs_get_knowledge_index',{'history':True},**kwargs)
        self.assertTrue(history['history'])
        self.assertEqual({r['revision'] for r in history['entries']},{'v1','v2'})
        self.assertEqual(self.adapter.call('fs_get_knowledge_index',{},**kwargs),current)
        self.assertNotIn('fc.idea',json.dumps(history))
        with self.assertRaisesRegex(ValueError,'history_type'):
            self.adapter.call('fs_get_knowledge_index',{'history':'false'},**kwargs)

    def test_index_keeps_conflicts_visible_and_schema_explains_history(self):
        self.index['entries'].append(dict(self.row,id='fc.disputed',status='conflict'))
        self.save_index();self.save_policy();self.prompt(self.info)
        index=self.adapter.call('fs_get_knowledge_index',{},session_id=self.info['session_id'],task_id='original-task-1')
        self.assertIn('fc.disputed',[r['id'] for r in index['entries']])
        ctx=Mock();register(ctx)
        schemas={c.kwargs['name']:c.kwargs['schema'] for c in ctx.register_tool.call_args_list}
        self.assertIn('history',schemas['fs_get_knowledge_index']['parameters']['properties'])
        self.assertIn('revision',schemas['fs_read_knowledge']['description'])
        self.assertIn('不要自报调用次数',self.adapter.prompt(self.info))
        self.assertIn('路径日期不代表文件修订或生效时间',self.adapter.prompt(self.info))

    def test_previous_unfiltered_index_receipt_is_preserved_but_not_reused(self):
        self.index['entries'].append(dict(self.row,revision='v1',layer='archive',status='retired'))
        self.save_index();self.save_policy();pin=self.adapter.pin(self.info)
        key=dict(session_id=self.info['session_id'],task_id='original-task-1',tool='fs_get_knowledge_index',args={})
        old_path=self.adapter._name('use',key)
        self.adapter._save(old_path,dict(identity=key,pin_sha256=pin['receipt_sha256'],result={'entries':pin['entries']}))
        before=(self.root/old_path).read_bytes()
        current=self.adapter.call('fs_get_knowledge_index',{},session_id=self.info['session_id'],task_id='original-task-1')
        self.assertEqual(len(current['entries']),1)
        self.assertEqual((self.root/old_path).read_bytes(),before)

    def test_conflicting_effective_rules_return_conflict(self):
        self.index['entries'].append(dict(self.row,revision='v3'));self.save_index();self.save_policy()
        self.prompt(self.info);self.assertEqual(self.read()['status'],'conflict')

    def test_source_missing_and_failed_release_keep_loaded_receipt(self):
        self.prompt(self.info);first=self.read()
        (self.folder/'rule.md').unlink()
        self.assertEqual(self.read(),first)
        with self.assertRaises(FileNotFoundError):self.read(entry_ids=['fc.rule'])
        self.index['release_state']='candidate';self.save_index();self.save_policy()
        with self.assertRaisesRegex(ValueError,'not_published'):self.adapter.pin(dict(self.info,session_id='next-session'))
        self.assertEqual(self.read(),first)

    def test_approved_test_ids_block_all_other_tools_and_task_spoofing(self):
        self.policy['native']['readonly_sessions']={'FS-new-1':{'task_ids':['readonly-task']}}
        self.save_policy()
        self.assertEqual(self.adapter.guard('terminal',{},session_id='FS-new-1',task_id='readonly-task')['action'],'block')
        kwargs=self.adapter.test_admission(self.info,'readonly-task')
        self.assertEqual(kwargs,dict(enabled_toolsets=['fs_knowledge'],skip_memory=True,skip_background_review=True))
        for tool in ['terminal','write_file','memory','skill_manage','execute_code','delegate_task','tool_call','fs_query_native_statistics','fs_reprice','unknown']:
            self.assertEqual(self.adapter.guard(tool,{},session_id='FS-new-1',task_id='readonly-task')['action'],'block')
        self.assertIsNone(self.adapter.guard('fs_read_knowledge',{},session_id='FS-new-1',task_id='readonly-task'))
        self.assertEqual(self.adapter.guard('fs_read_knowledge',{'task_id':'readonly-task'},session_id='FS-new-1',task_id='other')['action'],'block')
        with self.assertRaisesRegex(ValueError,'tool_fields'):
            self.adapter.call('fs_read_knowledge',{'modules':['FC27'],'session_id':'another'},session_id='FS-new-1',task_id='readonly-task')
        self.policy['native']['readonly_sessions']={};self.save_policy()
        self.assertEqual(self.adapter.guard('terminal',{},session_id='FS-new-1',task_id='readonly-task')['action'],'block')

    def test_normal_chats_keep_tools_even_when_policy_unavailable(self):
        self.prompt(self.info)
        self.assertIsNone(self.adapter.guard('terminal',{},session_id='FS-new-1',task_id='normal'))
        (self.root/'knowledge-load-policy.json').write_bytes(b'broken')
        self.assertIsNone(self.adapter.guard('terminal',{},session_id='unrelated',task_id='normal'))
        with self.assertRaises((ValueError,PermissionError)):
            self.adapter.test_admission(dict(self.info,session_id='new-test'),'test')

    def test_tampering_and_paths_do_not_fall_back_to_new_version(self):
        self.prompt(self.info);path=self.root/self.adapter._name('session','FS-new-1')
        v=json.loads(path.read_bytes());v['release']='injected';path.write_bytes(json.dumps(v).encode())
        with self.assertRaisesRegex(ValueError,'receipt_changed'):self.read()
        with self.assertRaisesRegex(ValueError,'identity'):self.adapter.bound('../other')

    def test_receipts_reconstruct_request_release_entries_and_hashes_without_business_db(self):
        self.prompt(self.info);v=self.read(entry_ids=['fc.rule'])
        uses=list((self.root/'knowledge/native').glob('use-*.json'));self.assertEqual(len(uses),1)
        r=json.loads(uses[0].read_bytes());self.assertEqual(r['identity']['task_id'],'original-task-1')
        self.assertEqual(r['result']['selection_sha256'],v['selection_sha256'])
        self.read(entry_ids=['fc.rule']);self.assertEqual(len(list((self.root/'knowledge/native').glob('use-*.json'))),1)
        self.assertFalse((self.root/'tasks.sqlite3').exists())

    def test_registration_has_official_hook_and_distinct_read_toolset(self):
        ctx=Mock();register(ctx)
        self.assertEqual(ctx.register_system_prompt_section.call_args.args[0],'fs.knowledge')
        self.assertEqual(ctx.register_system_prompt_section.call_args.kwargs['max_chars'],4000)
        self.assertEqual(ctx.register_hook.call_args.args[0],'pre_tool_call')
        self.assertEqual(ctx.register_tool.call_count,2)
        for c in ctx.register_tool.call_args_list:self.assertEqual(c.kwargs['toolset'],'fs_knowledge')

    def test_test_grants_are_typed_and_only_actual_fs_platforms_can_route(self):
        self.policy['native']['readonly_sessions']={'FS-new-1':{'task_ids':'substring-is-not-a-grant'}}
        self.save_policy()
        with self.assertRaisesRegex(ValueError,'test_tasks'):self.adapter.test_admission(self.info,'s')
        self.policy['native']['readonly_sessions']={};self.route['platform']='api_server';self.save_policy()
        info=dict(self.info,platform='api_server')
        self.assertEqual(self.prompt(info),'')
        self.route['platform']='tui';self.route['session_ids']=['other'];self.save_policy()
        info=dict(self.info,platform='tui');self.assertEqual(self.prompt(info),'')
        self.route['session_ids']=['FS-new-1'];self.save_policy();self.assertIn('offline-fixed',self.prompt(info))

    def test_actual_native_forwarding_symbol_binds_real_session_and_task(self):
        fixture=json.loads((Path(__file__).parent/'native-hook-fixture.json').read_bytes())
        namespace={};exec(fixture['symbol']['code'],namespace)
        self.policy['native']['readonly_sessions']={'FS-new-1':{'task_ids':['readonly-task']}}
        self.save_policy();self.adapter.test_admission(self.info,'readonly-task')
        module=types.ModuleType('hermes_cli.plugins')
        def dispatch(name,args,**ids):
            result=self.adapter.guard(name,args,**ids)
            return (result['message'] if result else None,None)
        module._dispatch_pre_tool_call_hooks=dispatch
        agent=types.SimpleNamespace(session_id='FS-new-1',_current_turn_id='turn',_current_api_request_id='api')
        with patch.dict(sys.modules,{'hermes_cli':types.ModuleType('hermes_cli'),'hermes_cli.plugins':module}):
            fn=namespace['_pre_tool_block_message']
            blocked,_=fn(agent,'terminal',{'session_id':'other'},'readonly-task','call',[])
            self.assertIn('只读',blocked)
            self.assertIsNone(fn(agent,'fs_read_knowledge',{},'readonly-task','call',[])[0])
            self.assertIsNotNone(fn(agent,'fs_read_knowledge',{},'different-task','call',[])[0])
            # Preserve evidence of the upstream outer fail-open; a prompt is not a permission boundary.
            module._dispatch_pre_tool_call_hooks=Mock(side_effect=RuntimeError('offline upstream failure'))
            self.assertIsNone(fn(agent,'terminal',{},'readonly-task','call',[])[0])

    def test_test_agent_has_only_read_tools_and_is_checked_before_model(self):
        self.policy['native']['readonly_sessions']={'FS-new-1':{'task_ids':['readonly-task']}}
        self.save_policy();record=[]
        def factory(**kw):
            record.append(kw)
            names={'fs_get_knowledge_index','fs_read_knowledge'}
            return types.SimpleNamespace(session_id=kw['session_id'],valid_tool_names=names,
                tools=[{'function':{'name':n}} for n in names])
        agent=self.adapter.test_agent(factory,self.info,'readonly-task',model='offline-fixture')
        self.assertEqual(record[0]['enabled_toolsets'],['fs_knowledge'])
        self.assertTrue(record[0]['skip_memory']);self.assertTrue(record[0]['skip_background_review'])
        agent.valid_tool_names.add('terminal')
        with self.assertRaisesRegex(PermissionError,'grants_changed'):
            self.adapter.verify_test_agent(agent,'FS-new-1','readonly-task')
        with self.assertRaises(PermissionError):self.adapter.test_agent(factory,self.info,'different-task')
        self.assertEqual(len(record),1)

    def test_concurrent_same_process_prompt_pin_is_idempotent(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            prompts=list(pool.map(lambda _:self.prompt(self.info),range(12)))
        self.assertEqual(len(set(prompts)),1)
        self.assertEqual(len(list((self.root/'knowledge/native').glob('session-*.json'))),1)

    def test_short_index_remains_valid_json_with_actual_native_limit(self):
        self.index['entries']=[dict(self.row,id='fc.rule'+str(i)) for i in range(100)]
        self.save_index();self.save_policy()
        prompt=self.prompt(self.info)
        self.assertLessEqual(len(prompt),4000)
        summary=json.loads(prompt.split('\n',1)[1])
        self.assertGreater(summary['additional_entries'],0)
        self.assertEqual(len(self.adapter.bound(self.info['session_id'])['entries']),100)


class PrivateReceipts(unittest.TestCase):
    save_index = Native.save_index
    save_policy = Native.save_policy

    def setUp(self):
        Native.setUp(self)
        private = tempfile.TemporaryDirectory()
        self.addCleanup(private.cleanup)
        self.receipts = Path(private.name)
        self.info.update(owner='approved-user')
        self.policy['task_routes'] = dict(enabled=True, routes=[dict(
            owner=self.info['owner'], project='FS', channel='desktop', task_types=['conversation'],
            profile_name=self.info['profile_name'], catalog=self.route['catalog'],
            sha256=self.route['sha256'], modules=['FC27'])])
        self.save_policy()

    def separate(self):
        return NativeKnowledge(self.root, receipt_root=self.receipts)

    def locked(self):
        host = self.separate()
        pin = host.pin_task(self.info, 'turn-1', 'turn-1')
        return host, pin

    def test_session_and_use_receipts_only_write_private_root(self):
        source = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        adapter = self.separate()
        adapter.pin(self.info)
        result = adapter.call('fs_read_knowledge', {'modules': ['FC27']},
                              session_id=self.info['session_id'], task_id='turn-1')
        self.assertEqual(result['entries'][0]['content'], 'current rule')
        self.assertFalse((self.root / 'knowledge/native').exists())
        self.assertEqual(len(list((self.receipts / 'knowledge/native').glob('use-*.json'))), 1)
        self.assertEqual({p.relative_to(self.root): p.read_bytes()
                          for p in self.root.rglob('*') if p.is_file()}, source)
        self.assertEqual(adapter.bound(self.info['session_id'])['release'], 'offline-fixed')

    def test_worker_loads_locked_turn_without_reselecting_current(self):
        host, pin = self.locked()
        worker = self.separate()
        self.policy['task_routes']['enabled'] = False
        self.save_policy()
        with patch.object(worker, 'task_selection', side_effect=AssertionError('must not reselect')):
            self.assertEqual(worker.load_task(self.info, 'turn-1', 'turn-1',
                expected_sha256=pin['receipt_sha256']), pin)
            with worker.activate_task(self.info, 'turn-1', 'turn-1', pin_sha256=pin['receipt_sha256']) as loaded:
                self.assertEqual(loaded, pin)
                result = worker.call('fs_read_knowledge', {'modules': ['FC27']},
                                     session_id=self.info['session_id'], task_id='turn-1')
                self.assertEqual(result['entries'][0]['content'], 'current rule')
                self.assertEqual(worker.call('fs_read_knowledge', {'modules': ['FC27']},
                    session_id=self.info['session_id'], task_id='turn-1'), result)
        self.assertIsNone(worker.active_task(self.info['session_id'], 'turn-1'))
        self.assertEqual(host.load_task(self.info, 'turn-1', 'turn-1',
            expected_sha256=pin['receipt_sha256']), pin)
        self.assertEqual(len(list((self.receipts / 'knowledge/native').glob('use-*.json'))), 1)

    def test_locked_pin_requires_original_scope_task_and_external_hash(self):
        adapter, pin = self.locked()
        for field in ('owner', 'platform', 'profile_name', 'chat_id', 'thread_id'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'task_identity'):
                adapter.load_task(dict(self.info, **{field: 'other'}), 'turn-1', 'turn-1',
                                  expected_sha256=pin['receipt_sha256'])
        with self.assertRaisesRegex(ValueError, 'task_identity'):
            adapter.load_task(self.info, 'turn-1', 'turn-2', expected_sha256=pin['receipt_sha256'])
        with self.assertRaisesRegex(ValueError, 'pin_changed'):
            adapter.load_task(self.info, 'turn-1', 'turn-1', expected_sha256='0' * 64)
        with self.assertRaises(FileNotFoundError):
            adapter.load_task(self.info, 'missing', 'missing', expected_sha256=pin['receipt_sha256'])
        self.assertFalse((self.receipts / adapter._name('active', self.info['session_id'])).exists())

    def test_activation_is_current_process_and_child_alias_cleans_up_on_failure(self):
        adapter, pin = self.locked()
        worker = self.separate()
        child = 'official-compacted-child'
        with self.assertRaisesRegex(RuntimeError, 'stop'):
            with worker.activate_task(self.info, 'turn-1', 'turn-1', pin_sha256=pin['receipt_sha256']):
                self.assertEqual(worker.active_task(self.info['session_id'], 'turn-1'), pin)
                with patch('fs_readonly.knowledge.os.getpid', return_value=-1):
                    with self.assertRaisesRegex(ValueError, 'active_task_mismatch'):
                        worker.active_task(self.info['session_id'], 'turn-1')
                alias = worker.link_task_session(pin, child, 'turn-1')
                try:
                    self.assertEqual(worker.active_task(child, 'turn-1'), pin)
                    self.assertEqual(worker.call('fs_get_knowledge_index', {}, session_id=child,
                        task_id='turn-1')['release'], pin['release'])
                    raise RuntimeError('stop')
                finally:
                    worker.unlink_task_session(alias, pin)
        self.assertIsNone(worker.active_task(child, 'turn-1'))
        self.assertIsNone(worker.active_task(self.info['session_id'], 'turn-1'))
        self.assertEqual(adapter.load_task(self.info, 'turn-1', 'turn-1',
            expected_sha256=pin['receipt_sha256']), pin)
        self.assertFalse((self.root / 'knowledge/native').exists())

    def test_missing_locked_pin_does_not_create_or_reselect_it(self):
        adapter = self.separate()
        with patch.object(adapter, 'task_selection', side_effect=AssertionError('must not reselect')):
            with self.assertRaises(FileNotFoundError):
                with adapter.activate_task(self.info, 'turn-1', 'turn-1', pin_sha256='0' * 64):
                    self.fail('missing pin activated')
        self.assertFalse(list(self.receipts.rglob('task-*.json')))
        self.assertFalse(list(self.receipts.rglob('active-*.json')))

    def test_receipt_tampering_and_owner_private_roots_do_not_fallback(self):
        adapter, pin = self.locked()
        other = NativeKnowledge(self.root, receipt_root=self.root / 'other-owner')
        with self.assertRaises(FileNotFoundError):
            other.load_task(self.info, 'turn-1', 'turn-1', expected_sha256=pin['receipt_sha256'])
        path = self.receipts / adapter._name('task', pin['identity'])
        changed = dict(pin, release='injected')
        path.write_text(json.dumps(changed), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'receipt_changed'):
            adapter.load_task(self.info, 'turn-1', 'turn-1', expected_sha256=pin['receipt_sha256'])

    def test_stale_process_alias_retires_only_after_locked_pin_is_validated(self):
        adapter, pin = self.locked()
        name = adapter._name('active', self.info['session_id'])
        stale = adapter._save(name, dict(session_id=self.info['session_id'], native_task_id='turn-1',
            pid=-1, pin=adapter._name('task', pin['identity']), pin_sha256=pin['receipt_sha256']))
        before = (self.receipts / name).read_bytes()
        worker = self.separate()
        with self.assertRaisesRegex(ValueError, 'pin_changed'):
            with worker.activate_task(self.info, 'turn-1', 'turn-1', pin_sha256='0' * 64):
                self.fail('wrong pin activated')
        self.assertEqual((self.receipts / name).read_bytes(), before)
        with worker.activate_task(self.info, 'turn-1', 'turn-1', pin_sha256=pin['receipt_sha256']):
            self.assertEqual(worker.active_task(self.info['session_id'], 'turn-1'), pin)
        self.assertIsNone(worker.active_task(self.info['session_id'], 'turn-1'))
        retired = worker._read(worker._name('retired-active', stale['receipt_sha256']))
        self.assertEqual(retired['previous_active'], stale)


if __name__=='__main__':unittest.main()
