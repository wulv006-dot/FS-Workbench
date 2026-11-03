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

    def test_native_title_response_format_reaches_provider_body_and_identity(self):
        # Fixed Hermes agent/title_generator.py _TITLE_RESPONSE_FORMAT. This is
        # the SDK auxiliary request shape, not another business task.
        title_format = {'type':'json_schema', 'json_schema':{'name':'session_title', 'strict':True,
            'schema':{'type':'object','properties':{'title':{'type':'string'}},
                      'required':['title'],'additionalProperties':False}}}
        with fixtures.MaterialTransport().fixture(material=False) as f:
            native, binding, schemas, active, scope = self.setup_native(f)
            body = dict(model='deepseek-flash', messages=[{'role':'user','content':'name this chat'}],
                        reasoning_effort='none', response_format=deepcopy(title_format))
            before = deepcopy(body)
            f.proxy.dispatch('POST','/v1/chat/completions',f.token,body)
            request = f.turns[-1]
            wire = f.module.request_body(request,'deepseek-flash',tool_schemas=schemas,native_chat=True)
            self.assertEqual(request['response_format'],title_format)
            self.assertEqual(wire['response_format'],title_format)
            self.assertEqual(wire['tools'],[])
            self.assertEqual(body,before)
            body['response_format']={'type':'json_object'}
            f.proxy.dispatch('POST','/v1/chat/completions',f.token,body)
            from pilot import digest
            self.assertNotEqual(digest(f.turns[0]),digest(f.turns[1]))
            self.assertEqual(f.gateway.call.call_count,2)

    def test_native_response_format_invalid_and_legacy_reject_before_ledger(self):
        invalid = [None, 'json', {}, {'type':'invented'}, {'type':'json_object','url':'file:///x'},
                   {'type':'json_schema','json_schema':{'name':'title','strict':1,'schema':{}}},
                   {'type':'json_schema','json_schema':{'name':'title','schema':[]}}]
        for value in invalid:
            with self.subTest(value=value), fixtures.MaterialTransport().fixture(material=False) as f:
                self.setup_native(f)
                body=dict(model='deepseek-flash', messages=[{'role':'user','content':'title'}],response_format=value)
                with self.assertRaises(ValueError): f.proxy.dispatch('POST','/v1/chat/completions',f.token,body)
                self.assertEqual(f.turns,[])
                f.gateway.call.assert_not_called()
        with fixtures.MaterialTransport().fixture(material=False) as f:
            body=dict(f.body,tools=f.module.schemas(),response_format={'type':'json_object'})
            with self.assertRaisesRegex(ValueError,'request_fields'):
                f.proxy.dispatch('POST','/v1/chat/completions',f.token,body)
            self.assertEqual(f.turns,[])
            f.gateway.call.assert_not_called()

    def test_native_title_format_survives_real_direct_provider_serialization(self):
        import json
        from unittest.mock import patch
        with fixtures.MaterialTransport().fixture(material=False) as f:
            self.setup_native(f)
            provider=fixtures.load('native_title_direct_provider',CORE/'direct_provider.py')
            token=f.grants.mint('fixture-owner','fixture-task','fixture-lease',reasoning_effort='high')
            response_format={'type':'json_schema','json_schema':{'name':'session_title','strict':True,
                'schema':{'type':'object','properties':{'title':{'type':'string'}},
                          'required':['title'],'additionalProperties':False}}}
            body={'messages':[{'role':'user','content':'title'}],'model':'deepseek-flash',
                  'reasoning_effort':'none','response_format':response_format}
            f.proxy.dispatch('POST','/v1/chat/completions',token,body)
            request=f.module.request_body(f.turns[0],provider.MODEL,
                tool_schemas=f.gateway.scope.schemas(),native_chat=True)
            wire=json.loads(provider.prepare_request(request,f.gateway.scope.schemas()))
            self.assertEqual(wire['response_format'],response_format)
            self.assertNotIn('tools',wire)
            self.assertEqual(wire['reasoning_effort'],'high')
            with patch.object(provider,'_open',return_value={'id':'title-response','model':provider.MODEL}) as send:
                provider.request_model(request,f.gateway.scope.schemas())
                self.assertEqual(json.loads(send.call_args.args[1])['response_format'],response_format)
                send.assert_called_once()
            bad=dict(request,response_format={'type':'invented'})
            with patch.object(provider,'_open') as send:
                self.assertEqual(provider.request_model(bad,f.gateway.scope.schemas())['status'],'configuration_invalid')
                send.assert_not_called()

    def test_native_trusted_reasoning_and_tool_choice_reach_real_provider_bytes(self):
        import json
        for effort in ('none','minimal','low','medium','high','xhigh','max','ultra'):
            with self.subTest(effort=effort), fixtures.MaterialTransport().fixture(material=False) as f:
                native,binding,schemas,active,old_scope=self.setup_native(f)
                scope=native.NativeChatScope(binding,lambda:active[0],model_schemas=lambda:schemas,
                                            reasoning_effort=lambda:effort)
                f.gateway.scope=scope
                provider=fixtures.load('capabilities_direct_provider',CORE/'direct_provider.py')
                for choice in ('auto','none','required',{'type':'function','function':{'name':'tool_call'}}):
                    body=dict(f.body,tools=deepcopy(schemas),reasoning_effort=effort,tool_choice=choice)
                    f.proxy.dispatch('POST','/v1/chat/completions',f.token,body)
                    request=f.module.request_body(f.turns[-1],provider.MODEL,tool_schemas=schemas,native_chat=True)
                    wire=json.loads(provider.prepare_request(request,schemas,native_chat=True))
                    self.assertEqual(wire['tool_choice'],choice)
                    self.assertEqual(wire['thinking']['type'],'disabled' if effort=='none' else 'enabled')
                    if effort!='none':self.assertEqual(wire['reasoning_effort'],effort)
                for changes in ({'reasoning_effort':'max' if effort!='max' else 'low'},
                                {'model':'unapproved-model'},
                                {'tool_choice':{'type':'function','function':{'name':'unknown'}}}):
                    before=len(f.turns)
                    with self.assertRaises(ValueError):f.proxy.dispatch('POST','/v1/chat/completions',f.token,dict(body,**changes))
                    self.assertEqual(len(f.turns),before)

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
            self.assertEqual(preflight.call_args.kwargs,{'native_chat':True})
            self.assertEqual(provider.call_args.kwargs,{'native_chat':True})
            self.assertEqual(one['choices'][0]['message']['tool_calls'], [call])
            self.assertEqual(gateway.transport_retries, 0)
            provider.return_value=dict(response,choices=[dict(message=dict(role='assistant',content='{"title":"Synthetic"}'),finish_reason='stop')])
            title_body=dict(model='deepseek-flash',messages=[{'role':'user','content':'title'}],
                            response_format={'type':'json_object'})
            title_one=f.proxy.dispatch('POST','/v1/chat/completions',f.token,title_body)
            title_two=f.proxy.dispatch('POST','/v1/chat/completions',f.token,title_body)
            self.assertEqual(title_one,title_two)
            self.assertEqual(provider.call_count,2)
            self.assertEqual(provider.call_args.args[0]['response_format'],{'type':'json_object'})
            next_body = dict(body, messages=[*body['messages'], dict(role='assistant', content=None, tool_calls=[call]),
                                          dict(role='tool',tool_call_id='call-native',content='done')])
            provider.side_effect = OSError('synthetic network outcome unknown')
            for expected in ('provider_outcome_unknown', 'unknown_previous_attempt'):
                with self.assertRaisesRegex(ValueError, '^'+expected+'$'):
                    f.proxy.dispatch('POST','/v1/chat/completions',f.token,next_body)
            self.assertEqual(provider.call_count, 3)
            with db() as connection:
                self.assertEqual(connection.execute('SELECT state FROM model_calls ORDER BY rowid').fetchall()[2][0], 'unknown')
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM hermes_turns').fetchone()[0], 3)
            active[0] = False
            with self.assertRaises(PermissionError): f.proxy.dispatch('POST','/v1/chat/completions',f.token,body)
            self.assertEqual(provider.call_count, 3)


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


class NativeToolHistory(unittest.TestCase):
    """Real gateway/SQLite/preflight; only the vendor HTTP and OS slot are fixtures."""
    from contextlib import contextmanager

    @contextmanager
    def history_fixture(self, effort='none', older=False):
        from contextlib import contextmanager
        from datetime import datetime, timezone
        from pathlib import Path
        from unittest.mock import patch
        import json, sqlite3, sys, tempfile
        with fixtures.MaterialTransport().fixture(material=False) as f, tempfile.TemporaryDirectory() as temp:
            native=fixtures.load('native_chat',CORE/'native_chat.py')
            direct=fixtures.load('direct_provider',CORE/'direct_provider.py')
            binding=dict(owner='fixture-owner',conversation_id='cid',turn_id='fixture-task',
                         request_id='request',session_id='session',lease='fixture-lease',run_id='run-fixture')
            schemas=[dict(type='function',function=dict(name=name,parameters=dict(type='object',properties={})))
                     for name in ('fs_track_customer','fs_describe_customer','tool_call')]
            scope=native.NativeChatScope(binding,lambda:True,model_schemas=lambda:schemas,reasoning_effort=lambda:effort)
            @contextmanager
            def db():
                conn=sqlite3.connect(str(Path(temp)/'daily.sqlite3'));conn.row_factory=sqlite3.Row
                try:
                    with conn:yield conn
                finally:conn.close()
            with db() as conn:
                conn.execute('CREATE TABLE model_calls(fingerprint TEXT PRIMARY KEY,day TEXT,state TEXT,content TEXT)')
            @contextmanager
            def slot(unused):yield True
            sys.modules['background'].import_background=Mock()
            sys.modules['source_projection']=SimpleNamespace(project_capture=Mock())
            sys.modules['fc_daily']=SimpleNamespace(provider_slot=slot,model_daily_limit=lambda:0)
            factory=fixtures.load('history_fs_inprocess',fixtures.ROOT/'releases/fc-coins/fc-review-channel-20261026/source/fs_inprocess.py')
            gateway=factory.native_gateway(SimpleNamespace(db=db,root=Path(temp)),scope,
                                           active_tasks=lambda:{('fixture-owner','fixture-task')})
            proxy=f.transport.Proxy(f.grants,lambda grant:gateway)
            calls=[dict(id='same-'+str(i),type='function',index=i,
                        function=dict(name=name,arguments='{"round":0}'))
                   for i,name in enumerate(('fs_track_customer','fs_describe_customer'))]
            responses=[deepcopy(calls)]
            wire=[]
            def send(path,payload,**kwargs):
                wire.append(json.loads(payload))
                batch=responses[len(wire)-1] if len(wire)<=len(responses) else None
                message=dict(role='assistant',content=None,tool_calls=deepcopy(batch)) if batch else dict(role='assistant',content='synthetic answer')
                return dict(id='response-'+str(len(wire)),model=direct.MODEL,
                            usage=dict(prompt_tokens=1,completion_tokens=1,total_tokens=2),
                            choices=[dict(message=message,finish_reason='tool_calls' if batch else 'stop')])
            body=dict(model=direct.MODEL,messages=[dict(role='user',content='current synthetic followup')],
                      tools=schemas,max_tokens=32,stream=True,stream_options={'include_usage':True},reasoning_effort=effort)
            def replay(batch):
                copied=deepcopy(batch)
                for call in copied:call.pop('index',None)
                return [dict(role='assistant',content=None,tool_calls=copied)]+[
                    dict(role='tool',tool_call_id=c['id'],content='synthetic result') for c in copied]
            if older:
                old=deepcopy(calls)
                for c in old:
                    c['function'].update(name='tool_call',arguments='{"old":true}')
                body['messages']=[dict(role='user',content='older conversation turn'),*replay(old),*body['messages']]
            with patch.object(direct,'_open',side_effect=send):
                yield SimpleNamespace(f=f,proxy=proxy,db=db,body=body,calls=calls,wire=wire,
                                      responses=responses,replay=replay)

    def dispatch(self,h):
        return h.proxy.dispatch('POST','/v1/chat/completions',h.f.token,deepcopy(h.body))

    def test_older_same_ids_do_not_bind_to_this_tasks_receipt(self):
        with self.history_fixture(older=True) as h:
            self.dispatch(h)
            h.body['messages']+=h.replay(h.calls)
            self.assertEqual(self.dispatch(h)['choices'][0]['message']['content'],'synthetic answer')
            self.assertEqual(len(h.wire),2)
            # Only current calls inherit this task's trusted stream indexes.
            self.assertTrue(all('index' not in c for c in h.wire[-1]['messages'][1]['tool_calls']))
            self.assertEqual([c['index'] for c in h.wire[-1]['messages'][-3]['tool_calls']],[0,1])

    def test_normal_two_calls_keep_semantic_json_and_native_effort(self):
        for effort in ('none','medium','high'):
            with self.subTest(effort=effort),self.history_fixture(effort) as h:
                self.dispatch(h)
                history=h.replay(h.calls)
                for c in history[0]['tool_calls']:c['function']['arguments']='{ "round" : 0 }'
                h.body['messages']+=history
                self.dispatch(h)
                self.assertEqual(len(h.wire),2)
                self.assertEqual(h.wire[-1]['thinking']['type'],'disabled' if effort=='none' else 'enabled')
                with h.db() as conn:
                    self.assertEqual([tuple(r) for r in conn.execute('SELECT r.turn,m.state FROM hermes_reservations r JOIN model_calls m ON r.fingerprint=m.fingerprint ORDER BY r.turn')],[(0,'succeeded'),(1,'succeeded')])

    def test_current_call_changes_cannot_fall_back_to_older_matching_ids(self):
        for change in ('name','arguments','index','id','missing','duplicate'):
            with self.subTest(change=change),self.history_fixture(older=True) as h:
                self.dispatch(h)
                history=h.replay(h.calls)
                if change=='name':history[0]['tool_calls'][0]['function']['name']='tool_call'
                elif change=='arguments':history[0]['tool_calls'][0]['function']['arguments']='{"round":1}'
                elif change=='index':history[0]['tool_calls'][0]['index']=9
                elif change=='id':
                    history[0]['tool_calls'][0]['id']='changed-id';history[1]['tool_call_id']='changed-id'
                elif change=='missing':history=[dict(role='user',content='new request with the paid reply absent')]
                elif change=='duplicate':history+=deepcopy(history)
                h.body['messages']+=history
                with self.assertRaisesRegex(ValueError,'^provider_tool_history_changed$'):self.dispatch(h)
                self.assertEqual(len(h.wire),1)
                with h.db() as conn:
                    self.assertEqual(conn.execute('SELECT COUNT(*) FROM hermes_reservations').fetchone()[0],1)

    def test_multiple_receipts_restore_in_order_even_when_ids_repeat(self):
        with self.history_fixture(older=True) as h:
            second=deepcopy(h.calls)
            for c in second:c['function']['arguments']='{"round":1}'
            h.responses.append(second)
            self.dispatch(h)
            h.body['messages']+=h.replay(h.calls)
            self.dispatch(h)
            h.body['messages']+=h.replay(second)
            self.dispatch(h)
            self.assertEqual(len(h.wire),3)
            with h.db() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM model_calls WHERE state='succeeded'").fetchone()[0],3)

    def test_missing_reply_does_not_borrow_an_identical_older_batch(self):
        with self.history_fixture(older=True) as h:
            h.body['messages'][1:4]=h.replay(h.calls)
            self.dispatch(h)
            h.body['messages'].append(dict(role='user',content='changed request without current paid reply'))
            with self.assertRaisesRegex(ValueError,'^provider_tool_history_changed$'):self.dispatch(h)
            self.assertEqual(len(h.wire),1)

    def test_no_guess_when_the_paid_request_prefix_cannot_be_verified(self):
        with self.history_fixture(older=True) as h:
            self.dispatch(h)
            h.body['messages']+=h.replay(h.calls)
            with h.db() as conn:
                conn.execute("UPDATE hermes_reservations SET request_digest=?",('0'*64,))
            with self.assertRaisesRegex(ValueError,'^provider_tool_history_changed$'):self.dispatch(h)
            self.assertEqual(len(h.wire),1)


class NativeCompactionHistory(unittest.TestCase):
    def fixture(self):
        return NativeToolHistory('runTest').history_fixture(older=True)

    def dispatch(self,h):
        return NativeToolHistory.dispatch(self,h)

    def gateway(self,h):
        return h.proxy.gateway_for(h.f.grants.resolve(h.f.token))

    def sdk_compact(self,h,count=1,keep_tail=False):
        # Execute pinned SDK assembly and its actual post-commit event body.
        # Summary text, window selection, diagnostic counters and persistence
        # side effects are fixtures; the compressed list is NOT hand-written.
        sdk=fixtures.load('native_sdk_compaction',CORE.parent/'fixtures/native_compaction_sdk_71d34bad.py')
        engine=sdk.SDKAssembler();engine._summary_has_user_turn=True
        original=deepcopy(h.body['messages'])
        if not keep_tail:original.append(dict(role='user',content='continue the same synthetic task'))
        start=len(original)-3 if keep_tail else len(original)-1
        result=engine._assemble_compressed(original,0,start,
            SimpleNamespace(tail_start=start,summary_indices=set()),sdk.SUMMARY_PREFIX+'\nSynthetic summary from provider fixture '+str(count)+'.')
        events=[]
        agent=SimpleNamespace(session_id='session',platform='api_server',tools=h.body['tools'],
                              _memory_manager=None,context_compressor=SimpleNamespace(compression_count=count),
                              log_prefix='',_emit_diagnostic_status=lambda *args:None,
                              event_callback=lambda *args:events.append(args))
        sdk._finish_compaction_boundary(agent,result,new_system_prompt='',old_session_id=None,
            in_place=True,compacted_in_place=True,session_commit_succeeded=True,
            defer_context_engine_notification=False,compression_made_progress=True,
            compression_used_fallback=False,compression_feasibility_skip=False,task_id='fixture-task')
        self.assertEqual(events,[('session:compress',dict(platform='api_server',session_id='session',
            old_session_id='',in_place=True,compression_count=count))])
        self.assertNotEqual(result,original)
        # Explicit wire-preparation dependency: official transport strips its
        # underscore persistence/summary scaffolding before sending JSON.
        h.body['messages']=[{k:v for k,v in m.items() if not k.startswith('_')} for m in result]

    def confirm(self,h,count=1):
        import native_chat
        self.assertTrue(callable(getattr(native_chat,'native_messages_sha256',None)),'native digest helper missing')
        gateway=self.gateway(h)
        self.assertTrue(callable(getattr(gateway,'confirm_native_compaction',None)),'trusted compaction confirmation missing')
        binding=gateway.scope.context('fixture-owner','fixture-task','fixture-lease')
        value=native_chat.native_messages_sha256(h.body,reasoning_effort='none')
        receipt=gateway.confirm_native_compaction(binding,count,value)
        self.assertEqual(receipt,dict(registered=True,compression_count=count))
        return binding,value

    def test_official_compaction_without_trusted_confirmation_stays_rejected(self):
        with self.fixture() as h:
            self.dispatch(h);h.body['messages']+=h.replay(h.calls)
            self.sdk_compact(h)
            with self.assertRaisesRegex(ValueError,'provider_tool_history_changed'):self.dispatch(h)
            self.assertEqual(len(h.wire),1)

    def test_paid_tools_official_compaction_then_more_paid_tools_complete(self):
        for keep_tail in (False,True):
            with self.subTest(keep_tail=keep_tail),self.fixture() as h:
                newer=deepcopy(h.calls)
                for c in newer:c['function']['arguments']='{"round":1}'
                h.responses.append(newer)
                self.dispatch(h);h.body['messages']+=h.replay(h.calls)
                self.sdk_compact(h,keep_tail=keep_tail);self.confirm(h)
                self.dispatch(h);h.body['messages']+=h.replay(newer)
                self.assertEqual(self.dispatch(h)['choices'][0]['message']['content'],'synthetic answer')
                self.assertEqual(len(h.wire),3)
                with h.db() as conn:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM model_calls WHERE state='succeeded'").fetchone()[0],3)

    def test_first_compacted_request_and_retained_tail_are_hash_bound(self):
        for change in ('summary','retained_arguments'):
            with self.subTest(change=change),self.fixture() as h:
                self.dispatch(h);h.body['messages']+=h.replay(h.calls)
                self.sdk_compact(h,keep_tail=True);self.confirm(h)
                if change=='summary':h.body['messages'][0]['content']+=' changed'
                else:
                    next(m for m in h.body['messages'] if m.get('tool_calls'))['tool_calls'][0]['function']['arguments']='{"changed":true}'
                with self.assertRaisesRegex(ValueError,'provider_tool_history_changed'):self.dispatch(h)
                self.assertEqual(len(h.wire),1)

    def test_confirmation_replay_cannot_retire_later_receipt_or_unlock_baseline(self):
        for change in ('arguments','name','id','index','missing','duplicate','baseline'):
            with self.subTest(change=change),self.fixture() as h:
                newer=deepcopy(h.calls)
                for c in newer:c['function']['arguments']='{"round":1}'
                h.responses.append(newer)
                self.dispatch(h);h.body['messages']+=h.replay(h.calls)
                self.sdk_compact(h);binding,value=self.confirm(h)
                self.dispatch(h)
                self.gateway(h).confirm_native_compaction(binding,1,value)
                h.body['messages']+=h.replay(newer)
                if change=='arguments':h.body['messages'][-3]['tool_calls'][0]['function']['arguments']='{"changed":true}'
                elif change=='name':h.body['messages'][-3]['tool_calls'][0]['function']['name']='tool_call'
                elif change=='id':
                    h.body['messages'][-3]['tool_calls'][0]['id']='changed-id';h.body['messages'][-2]['tool_call_id']='changed-id'
                elif change=='index':h.body['messages'][-3]['tool_calls'][0]['index']=9
                elif change=='missing':
                    del h.body['messages'][-3:];h.body['messages'].append(dict(role='user',content='new request missing paid tool reply'))
                elif change=='duplicate':h.body['messages']+=deepcopy(h.body['messages'][-3:])
                else:h.body['messages'][0]['content']+=' changed'
                with self.assertRaisesRegex(ValueError,'provider_tool_history_changed'):self.dispatch(h)
                self.assertEqual(len(h.wire),2)

    def test_second_official_compaction_uses_only_new_server_watermark(self):
        with self.fixture() as h:
            for round_ in (1,2):
                newer=deepcopy(h.calls)
                for c in newer:c['function']['arguments']='{"round":'+str(round_)+'}'
                h.responses.append(newer)
            self.dispatch(h);h.body['messages']+=h.replay(h.calls)
            self.sdk_compact(h);binding,old=self.confirm(h)
            self.dispatch(h);h.body['messages']+=h.replay(h.responses[1])
            self.sdk_compact(h,count=2);self.confirm(h,count=2)
            with self.assertRaises(ValueError):self.gateway(h).confirm_native_compaction(binding,1,old)
            self.dispatch(h);h.body['messages']+=h.replay(h.responses[2])
            self.dispatch(h)
            self.assertEqual(len(h.wire),4)

    def test_compaction_confirmation_requires_native_exact_binding_and_live_rights(self):
        with self.fixture() as h:
            self.dispatch(h);h.body['messages']+=h.replay(h.calls);self.sdk_compact(h)
            binding,value=self.confirm(h)
            gateway=self.gateway(h)
            for field in ('owner','conversation_id','turn_id','request_id','session_id','lease','run_id'):
                with self.subTest(field=field),self.assertRaises(PermissionError):
                    gateway.confirm_native_compaction(dict(binding,**{field:'forged'}),2,value)
            for count,hash_ in ((True,value),(0,value),(1,'f'*64)):
                with self.assertRaises(ValueError):gateway.confirm_native_compaction(binding,count,hash_)
            native_scope=gateway.scope
            gateway.scope=h.f.gateway.scope
            with self.assertRaises(PermissionError):gateway.confirm_native_compaction(binding,2,value)
            gateway.scope=native_scope
            before=deepcopy(gateway._native_compaction)
            rights=iter((True,False));gateway.scope._authorize=lambda:next(rights)
            with self.assertRaises(PermissionError):gateway.confirm_native_compaction(binding,2,value)
            self.assertEqual(gateway._native_compaction,before)
            gateway.scope._authorize=lambda:False
            with self.assertRaises(PermissionError):gateway.confirm_native_compaction(binding,2,value)

    def test_unsettled_and_orphan_reservations_cannot_be_retired(self):
        for state in ('started','unknown',None):
            with self.subTest(state=state),self.fixture() as h:
                self.dispatch(h);h.body['messages']+=h.replay(h.calls);self.sdk_compact(h)
                with h.db() as conn:
                    if state is None:conn.execute('DELETE FROM model_calls')
                    else:conn.execute('UPDATE model_calls SET state=?',(state,))
                with self.assertRaisesRegex(ValueError,'native_compaction_unsettled'):self.confirm(h)
                self.assertIsNone(self.gateway(h)._native_compaction)

    def test_rebuilt_gateway_has_no_compaction_authority_and_no_body_field_can_create_it(self):
        with self.fixture() as h:
            self.dispatch(h);h.body['messages']+=h.replay(h.calls);self.sdk_compact(h);self.confirm(h)
            old=self.gateway(h)
            fresh=type(old)(old.scope,old.budget,old.slot,old.provider,old.input_bound,old.daily_limit,preflight=old.preflight)
            h.proxy.gateway_for=lambda grant:fresh
            with self.assertRaisesRegex(ValueError,'provider_tool_history_changed'):self.dispatch(h)
            self.assertEqual(len(h.wire),1)
            h.body['compression_count']=1;h.body['messages_sha256']='f'*64
            with self.assertRaisesRegex(ValueError,'request_fields'):self.dispatch(h)

    def test_native_digest_matches_actual_transport_carrier_normalization(self):
        with self.fixture() as h:
            import native_chat
            from pilot import digest
            messages=[dict(role='user',content='synthetic'),dict(role='assistant',content='answer',
                      reasoning='',reasoning_content=''),dict(role='user',content='continue')]
            identity=native_chat.native_messages_sha256(dict(messages=messages),reasoning_effort='none')
            self.assertEqual(identity,
                digest([dict(role='user',content='synthetic'),dict(role='assistant',content='answer'),dict(role='user',content='continue')]))
            h.body['messages']=deepcopy(messages);self.dispatch(h)
            self.assertEqual(identity,digest(h.wire[0]['messages']))
            messages[1]['reasoning']='different'
            with self.assertRaisesRegex(ValueError,'reasoning_carrier_mismatch'):
                native_chat.native_messages_sha256(dict(messages=messages),reasoning_effort='none')


if __name__ == '__main__':
    unittest.main()
