"""Native chat uses a host-bound scope and the actual SDK tool surface."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import test_material_transport as fixtures

CORE = fixtures.CORE


class NativeChat(unittest.TestCase):
    def setup_native(self, f):
        path = CORE / 'native_chat.py'
        self.assertTrue(path.exists(), 'native chat scope is missing')
        native = fixtures.load('native_chat', path)
        binding = dict(owner='fixture-owner', conversation_id='fixture-cid', turn_id='fixture-task',
                       request_id='fixture-request', session_id='native-session', lease='fixture-lease', run_id='run-native')
        schemas = [dict(type='function', function=dict(name=name, description='SDK schema',
                   parameters=dict(type='object', properties={})))
                   for name in ('tool_search', 'tool_describe', 'tool_call')]
        active = [True]
        scope = native.NativeChatScope(binding, lambda: active[0], model_schemas=lambda: schemas)
        f.gateway.scope = scope
        return native, binding, schemas, active, scope

    def test_scope_has_no_fc_task_or_snapshot_and_requires_current_literal_true(self):
        with fixtures.MaterialTransport().fixture(material=False) as f:
            native, binding, schemas, active, scope = self.setup_native(f)
            self.assertEqual(scope.context(binding['owner'], binding['turn_id'], binding['lease']), binding)
            for key in ('fixture-other', '', None):
                with self.assertRaises(PermissionError): scope.context(key, binding['turn_id'], binding['lease'])
            for value in (1, 'false', {'allowed': False}, False, None):
                active[0] = value
                with self.assertRaises(PermissionError): scope.context(binding['owner'], binding['turn_id'], binding['lease'])
            active[0] = True
            with self.assertRaises(PermissionError): scope.context(binding['owner'], binding['turn_id'], 'old-lease')
            with self.assertRaises(PermissionError): scope.call(binding['owner'], binding['turn_id'], binding['lease'], 'read_file', {})

    def test_tool_surface_is_host_bound_immutable_and_not_request_selected(self):
        with fixtures.MaterialTransport().fixture(material=False) as f:
            native, binding, schemas, active, scope = self.setup_native(f)
            result = scope.schemas()
            result[0]['function']['description'] = 'client mutation'
            self.assertEqual(scope.schemas(), schemas)
            schemas[0]['function']['parameters']['properties']['injected'] = {'type': 'string'}
            with self.assertRaises(PermissionError): scope.schemas()

    def test_native_stream_discovery_request_reaches_gateway_unchanged(self):
        with fixtures.MaterialTransport().fixture(material=False) as f:
            native, binding, schemas, active, scope = self.setup_native(f)
            body = dict(f.body, tools=deepcopy(schemas), stream=True, stream_options={'include_usage': True})
            result = f.proxy.dispatch('POST', '/v1/chat/completions', f.token, body)
            self.assertEqual(result['choices'][0]['message']['content'], 'synthetic')
            self.assertEqual(len(f.turns), 1)
            self.assertEqual(f.gateway.call.call_args.args[-1]['tools'], schemas)
            self.assertNotIn('period', f.gateway.call.call_args.args[-1])
            self.assertNotIn('snapshot_id', f.gateway.call.call_args.args[-1])

    def test_forged_same_name_schema_rejected_before_ledger(self):
        with fixtures.MaterialTransport().fixture(material=False) as f:
            native, binding, schemas, active, scope = self.setup_native(f)
            body = dict(f.body, tools=deepcopy(schemas))
            body['tools'][0]['function']['parameters']['properties']['file'] = {'type':'string'}
            with self.assertRaises(ValueError): f.proxy.dispatch('POST', '/v1/chat/completions', f.token, body)
            self.assertEqual(f.turns, [])
            f.gateway.call.assert_not_called()

    def test_native_multimodal_content_and_tool_history_keep_actual_surface(self):
        with fixtures.MaterialTransport().fixture(material=False) as f:
            native, binding, schemas, active, scope = self.setup_native(f)
            call = dict(id='call-native', type='function', function=dict(name='tool_call', arguments='{}'))
            messages = [dict(role='user', content=[dict(type='text', text='see attachment'),
                        dict(type='image_url', image_url={'url':'data:image/png;base64,aGVsbG8='})]),
                        dict(role='assistant', content=None, tool_calls=[call]),
                        dict(role='tool', tool_call_id='call-native', content='ok')]
            body = dict(f.body, messages=messages, tools=deepcopy(schemas), stream=True)
            f.proxy.dispatch('POST', '/v1/chat/completions', f.token, body)
            self.assertEqual(f.turns[0]['messages'], messages)
            wire = f.module.request_body(f.turns[0], 'deepseek-flash', tool_schemas=schemas, native_chat=True)
            self.assertEqual(wire['messages'], messages)
            self.assertEqual(wire['tools'], schemas)
            for content in ([{'type':'input_file','file_id':'invented'}], [{'type':'image_url','image_url':{'url':'file:///secret'}}]):
                invalid = dict(f.turns[0], messages=[dict(role='user', content=content)])
                with self.assertRaises(ValueError): f.module.request_body(invalid, 'deepseek-flash', tool_schemas=schemas, native_chat=True)

    def test_native_provider_response_validation_uses_dynamic_names(self):
        with fixtures.MaterialTransport().fixture(material=False) as f:
            native, binding, schemas, active, scope = self.setup_native(f)
            call = dict(id='call-native', type='function', function=dict(name='tool_call', arguments='{}'))
            f.module.validate_tool_call(call, tool_schemas=schemas)
            with self.assertRaises(ValueError): f.module.validate_tool_call(call)
            with self.assertRaises(ValueError):
                f.module.validate_tool_call(dict(call, function=dict(name='shell_unregistered', arguments='{}')), tool_schemas=schemas)

    def test_native_compression_stream_does_not_require_fake_tools(self):
        with fixtures.MaterialTransport().fixture(material=False) as f:
            native, binding, schemas, active, scope = self.setup_native(f)
            body = dict(model='deepseek-flash', messages=[{'role':'user','content':'compact this history'}],
                        stream=True, stream_options={'include_usage':True})
            f.proxy.dispatch('POST','/v1/chat/completions',f.token,body)
            request = f.gateway.call.call_args.args[-1]
            self.assertEqual(request['tools'], [])
            self.assertTrue(request['auxiliary'])

    def test_unbound_run_and_duplicate_surface_cannot_admit(self):
        with fixtures.MaterialTransport().fixture(material=False) as f:
            native, binding, schemas, active, scope = self.setup_native(f)
            for key in binding:
                invalid = dict(binding, **{key: None})
                with self.assertRaises(ValueError): native.NativeChatScope(invalid, lambda: True, model_schemas=lambda: schemas)
            bad = native.NativeChatScope(binding, lambda: True, model_schemas=lambda: schemas + [schemas[0]])
            with self.assertRaises(ValueError): bad.schemas()


    def test_native_text_is_not_censored_as_if_it_were_server_config(self):
        with fixtures.MaterialTransport().fixture(material=False) as f:
            native, binding, schemas, active, scope = self.setup_native(f)
            text = 'Explain this synthetic example: password=example; Cookie: test'
            body = dict(f.body, tools=schemas, messages=[{'role':'user','content':text}])
            f.proxy.dispatch('POST', '/v1/chat/completions', f.token, body)
            self.assertEqual(f.turns[0]['messages'][0]['content'], text)

    def test_native_factory_uses_real_budget_replay_and_unknown_hold(self):
        from contextlib import contextmanager
        from datetime import datetime, timezone
        import sqlite3
        import tempfile
        from pathlib import Path
        import sys
        with fixtures.MaterialTransport().fixture(material=False) as f, tempfile.TemporaryDirectory() as folder:
            native, binding, schemas, active, scope = self.setup_native(f)
            @contextmanager
            def db():
                connection = sqlite3.connect(str(Path(folder) / 'daily.sqlite3'))
                connection.row_factory = sqlite3.Row
                try:
                    yield connection
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
                finally:
                    connection.close()
            with db() as connection:
                connection.execute('CREATE TABLE model_calls (fingerprint TEXT PRIMARY KEY,day TEXT,state TEXT,content TEXT)')
            @contextmanager
            def slot(root):
                yield True
            call = dict(id='call-native', type='function', function=dict(name='tool_call', arguments='{}'))
            response = dict(id='receipt-native', model='deepseek-flash',
                usage={'prompt_tokens':2,'completion_tokens':3,'total_tokens':5},
                choices=[dict(message=dict(role='assistant',content=None,tool_calls=[call]),finish_reason='tool_calls')])
            provider = Mock(return_value=response)
            preflight = Mock(return_value=b'synthetic-wire')
            sys.modules['fc_daily'] = SimpleNamespace(provider_slot=slot, model_daily_limit=lambda: 0)
            sys.modules['direct_provider'] = SimpleNamespace(MODEL='deepseek-flash',
                POLICY_ID='no-pilot-quotas-deepseek-direct-stream-tokens-only-v2',
                request_model=provider, prepare_request=preflight)
            sys.modules['background'].import_background = Mock()
            sys.modules['source_projection'] = SimpleNamespace(project_capture=Mock())
            factory = fixtures.load('native_fs_inprocess', fixtures.ROOT / 'releases/fc-coins/fc-review-channel-20261026/source/fs_inprocess.py')
            self.assertTrue(callable(getattr(factory, 'native_gateway', None)), 'native budget factory is missing')
            gateway = factory.native_gateway(SimpleNamespace(db=db,root=Path(folder)), scope,
                                             active_tasks=lambda: {(binding['owner'],binding['turn_id'])})
            f.proxy = f.transport.Proxy(f.grants, lambda grant: gateway)
            body = dict(f.body, tools=schemas, stream=True)
            one = f.proxy.dispatch('POST','/v1/chat/completions',f.token,body)
            two = f.proxy.dispatch('POST','/v1/chat/completions',f.token,body)
            self.assertEqual(one, two)
            self.assertEqual(provider.call_count, 1)
            self.assertEqual(preflight.call_args.args[1], schemas)
            self.assertEqual(one['choices'][0]['message']['tool_calls'], [call])
            self.assertEqual(gateway.transport_retries, 0)
            next_body = dict(body, messages=[*body['messages'], dict(role='assistant', content=None, tool_calls=[call]),
                                          dict(role='tool',tool_call_id='call-native',content='done')])
            provider.side_effect = OSError('synthetic network outcome unknown')
            for expected in ('provider_outcome_unknown', 'unknown_previous_attempt'):
                with self.assertRaisesRegex(ValueError, '^'+expected+'$'):
                    f.proxy.dispatch('POST','/v1/chat/completions',f.token,next_body)
            self.assertEqual(provider.call_count, 2)
            with db() as connection:
                self.assertEqual(connection.execute('SELECT state FROM model_calls ORDER BY rowid').fetchall()[1][0], 'unknown')
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM hermes_turns').fetchone()[0], 2)
            active[0] = False
            with self.assertRaises(PermissionError): f.proxy.dispatch('POST','/v1/chat/completions',f.token,body)
            self.assertEqual(provider.call_count, 2)


    def test_submit_hold_counts_native_and_legacy_inflight_without_settling_usage(self):
        from contextlib import contextmanager
        from datetime import datetime, timezone
        import inspect
        import sqlite3
        import sys
        import tempfile
        from pathlib import Path
        with fixtures.MaterialTransport().fixture(material=False) as f, tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            tasks=sys.modules['pilot'].TaskStore(root/'tasks.sqlite3')
            with tasks.db() as connection:
                connection.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?)',
                    ('legacy-task','fixture-owner','legacy-fingerprint','{}','RUNNING',1,'run-legacy','legacy-lease',0,0))
            @contextmanager
            def daily_db():
                connection=sqlite3.connect(str(root/'daily.sqlite3'));connection.row_factory=sqlite3.Row
                try:
                    with connection:yield connection
                finally:connection.close()
            with daily_db() as connection:
                connection.execute('CREATE TABLE model_calls(fingerprint TEXT PRIMARY KEY,day TEXT,state TEXT,content TEXT)')
            policy=dict(id='no-pilot-quotas-deepseek-direct-stream-tokens-only-v2',model='deepseek-flash',
                        price_version='deepseek-direct-no-cny-invoice-or-fx-v1',input_microcny=None,output_microcny=None)
            budget=f.module.UnifiedBudget(daily_db,policy,lambda:datetime.now(timezone.utc),allow_unknown_costs=True)
            budget.active_tasks=lambda:{('fixture-owner','native-other-cid'),('fixture-owner','legacy-task')}
            request=dict(messages=[dict(role='user',content='synthetic')],max_tokens=32)
            for task in ('native-other-cid','legacy-task'):
                budget.reserve('fixture-owner',task,0,request,100,0)
            sys.modules['background'].import_background=Mock()
            sys.modules['source_projection']=SimpleNamespace(project_capture=Mock())
            factory=fixtures.load('native_hold_fs_inprocess',fixtures.ROOT/'releases/fc-coins/fc-review-channel-20261026/source/fs_inprocess.py')
            daily=SimpleNamespace(db=daily_db)
            self.assertEqual(factory.spending_hold(daily,tasks,'fixture-owner'),'pilot_usage_hold')
            self.assertIn('active_tasks',inspect.signature(factory.spending_hold).parameters,'native submit hold lacks server callback')
            callback=Mock(return_value={('fixture-owner','native-other-cid')})
            self.assertIsNone(factory.spending_hold(daily,tasks,'fixture-owner',active_tasks=callback))
            callback.assert_called_once_with()
            # Old controller and FC gateway do not pass native-only keyword arguments.
            tasks._native_active_model_tasks=callback
            self.assertIsNone(factory.spending_hold(daily,tasks,'fixture-owner'))
            self.assertEqual(factory.active_model_tasks(tasks),{('fixture-owner','native-other-cid'),('fixture-owner','legacy-task')})
            @contextmanager
            def slot(unused):yield True
            provider=Mock()
            sys.modules['fc_daily']=SimpleNamespace(provider_slot=slot,model_daily_limit=lambda:0)
            sys.modules['direct_provider']=SimpleNamespace(MODEL=policy['model'],POLICY_ID=policy['id'],
                request_model=provider,prepare_request=Mock())
            with tasks.db() as connection:
                connection.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?)',
                    ('legacy-next','fixture-owner','next-fingerprint','{}','RUNNING',1,'run-next','next-lease',0,0))
            fc_gateway=factory.gateway(SimpleNamespace(db=daily_db,root=root),tasks,SimpleNamespace(capture_id='legacy-capture'))
            self.assertEqual(fc_gateway.budget.active_tasks(),factory.active_model_tasks(tasks))
            fc_gateway.budget.reserve('fixture-owner','legacy-next',0,request,100,0)
            provider.assert_not_called()
            del tasks._native_active_model_tasks
            for active in (set(),{('another-owner','native-other-cid')}):
                self.assertEqual(factory.spending_hold(daily,tasks,'fixture-owner',active_tasks=lambda:active),'pilot_usage_hold')
            with tasks.db() as connection:
                connection.execute("UPDATE tasks SET state='CANCEL_REQUESTED'")
            self.assertEqual(factory.spending_hold(daily,tasks,'fixture-owner',active_tasks=callback),'pilot_usage_hold')
            for invalid in (1,'true',{'allow':True}):
                with self.assertRaises(ValueError):factory.spending_hold(daily,tasks,'fixture-owner',active_tasks=invalid)
            with self.assertRaises(OSError):
                factory.spending_hold(daily,tasks,'fixture-owner',active_tasks=Mock(side_effect=OSError('ledger unavailable')))
            with daily_db() as connection:
                rows=connection.execute('SELECT m.state,r.microcny FROM model_calls m JOIN hermes_reservations r ON r.fingerprint=m.fingerprint').fetchall()
                self.assertEqual([tuple(row) for row in rows],[('started',-1),('started',-1),('started',-1)])


if __name__ == '__main__':
    unittest.main()
