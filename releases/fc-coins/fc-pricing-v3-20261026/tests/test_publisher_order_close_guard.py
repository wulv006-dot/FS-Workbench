"""Exercise the original publisher guard functions against a real read-only ledger."""
import ast,json,sqlite3,sys,tempfile,unittest,os,re,shutil,urllib.request
from contextlib import contextmanager,ExitStack,closing
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
from fc_pricing_v3.order_close import TERMINAL_LEDGER_STATUS
from fc_pricing_v3.order_close import execution_is_unresolved,ledger_operation_status

def function(path,name,scope):
    node=next(n for n in ast.parse(path.read_text('utf-8')).body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),scope)
    return scope[name]

class PublisherOrderCloseGuard(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'v3').mkdir()
        self.db=sqlite3.connect(self.root/'v3/control.sqlite3');self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE operations(id TEXT PRIMARY KEY, body TEXT)')
        self.execution='5cf3f55c-0305-4c1d-a169-a6e259a83536'
        self.read=function(SOURCE/'price_writer.py','ledger_operation_status',dict(ROOT=self.root/'missing-container-root',Path=Path,json=json))
        self.resolved=function(SOURCE/'automation_tick.py','resolved_execution',dict(ROOT=self.root))
        self.module=patch.dict(sys.modules,price_writer=SimpleNamespace(ledger_operation_status=self.read));self.module.start();self.addCleanup(self.module.stop)
    def ledger(self,status):
        self.db.execute('INSERT OR REPLACE INTO operations VALUES(?,?)',(self.execution,json.dumps({'status':status})));self.db.commit()
    def audit(self,**changes):
        return dict(dict(status='ORDER_ADMIN_CONFIRMED',ledger_status='COMPLETED',execution_id=self.execution),**changes)
    def test_only_matching_terminal_ledger_readback_resolves_order_admin_receipt(self):
        for status in TERMINAL_LEDGER_STATUS:
            with self.subTest(status=status):
                self.ledger(status);self.assertTrue(self.resolved(self.audit(ledger_status=status)))
    def test_explicit_host_root_reads_ledger_without_changing_container_default(self):
        self.ledger('COMPLETED')
        self.assertIsNone(self.read(self.execution))
        self.assertIsNone(self.read(self.execution,root=self.root/'wrong-host-root'))
        self.assertEqual(self.read(self.execution,root=self.root),'COMPLETED')
        self.assertTrue(self.resolved(self.audit()))
    def test_missing_or_conflicting_ledger_and_unknown_audit_still_block(self):
        self.assertFalse(self.resolved(self.audit()))
        for status in ('UNKNOWN','RUNNING','NO_CHANGE'):
            self.ledger(status);self.assertFalse(self.resolved(self.audit()))
        self.ledger('COMPLETED')
        for changes in ({'execution_id':None},{'execution_id':'different-operation'},{'ledger_status':None},{'ledger_status':'UNKNOWN'},{'status':'PARTIAL'}):
            with self.subTest(changes=changes):self.assertFalse(self.resolved(self.audit(**changes)))
    def test_existing_receipts_and_prewrite_rejection_keep_original_behavior(self):
        for status in ('CONFIRMED','RESTORED','CHECK_ONLY'):
            self.assertTrue(self.resolved({'status':status}))
        self.assertTrue(self.resolved({'status':'FAILED_BEFORE_WRITE','changed':False}))
        self.assertFalse(self.resolved({'status':'FAILED_BEFORE_WRITE','changed':True}))

    def test_public_compatibility_requires_original_completed_operation_and_close_reason(self):
        good=dict(operation_id=self.execution,status='COMPLETED',order_close={'reason':'order_write_confirmed_admin_price_matched'})
        for changes,wanted in (({},True),({'operation_id':'other'},False),({'status':'UNKNOWN'},False),
                               ({'status':'RUNNING'},False),({'order_close':{}},False),
                               ({'order_close':{'reason':'public_price_matched'}},False)):
            with self.subTest(changes=changes):
                body=dict(good,**changes)
                self.db.execute('INSERT OR REPLACE INTO operations VALUES(?,?)',(self.execution,json.dumps(body)));self.db.commit()
                state=self.audit(status='PUBLIC_CONFIRMED')
                self.assertEqual(self.resolved(state),wanted)
                terminal=ledger_operation_status(self.execution,root=self.root,require_order_admin_close=True)
                self.assertEqual(execution_is_unresolved(state,terminal),not wanted)
        self.assertFalse(self.resolved(self.audit(status='PUBLIC_CONFIRMED',ledger_status='UNKNOWN')))
        self.assertFalse(self.resolved(self.audit(status='PUBLIC_CONFIRMED',execution_id='other')))

    def test_real_writer_preflight_blocks_public_unknown_before_any_backend_hook(self):
        from unittest.mock import Mock
        from fc_pricing_v3 import dispatch
        (self.root/'executions').mkdir()
        state=self.audit(status='PUBLIC_CONFIRMED')
        (self.root/'executions'/(self.execution+'.json')).write_text(json.dumps(state))
        hook=Mock(side_effect=ValueError('next_guard_reached'))
        ns=dict(ROOT=self.root,Path=Path,json=json,re=re,PLATFORMS=('PS','XBOX','PC'),parse_uuid=lambda value:value,
                read_json=lambda p:json.loads(p.read_text()),load_authorized=lambda _:({},{}),load_policy=lambda:{'revision':1},
                check_write=lambda *a,**k:[],hooks_before_write=hook,execution_is_unresolved=execution_is_unresolved,
                ledger_operation_status=lambda ident,**kw:ledger_operation_status(ident,root=self.root,**kw))
        execute=function(SOURCE/'price_writer.py','execute',ns)
        for status,reason in (('UNKNOWN','unresolved_execution_exists'),('COMPLETED','next_guard_reached')):
            body=dict(operation_id=self.execution,status=status,order_close={'reason':'order_write_confirmed_admin_price_matched'})
            self.db.execute('INSERT OR REPLACE INTO operations VALUES(?,?)',(self.execution,json.dumps(body)));self.db.commit()
            hook.reset_mock()
            with patch.object(dispatch,'validate_dispatch'),self.assertRaisesRegex(ValueError,reason):
                execute('preview','new-operation','wulv',['PS'],policy_revision=1)
            self.assertEqual(hook.call_count,int(status=='COMPLETED'))

    def test_candidate_health_reads_same_sqlite_without_browser_writer_import(self):
        (self.root/'executions').mkdir();(self.root/'queue').mkdir();(self.root/'runs').mkdir()
        path=self.root/'executions'/(self.execution+'.json')
        path.write_text(json.dumps(self.audit(status='PUBLIC_CONFIRMED')))
        ns=dict(ROOT=self.root,os=os,datetime=datetime,timezone=timezone,urllib=__import__('urllib'),shutil=shutil,
                writer_status=lambda:'ready',certificate_health=lambda:{},valid_id=lambda _:False,
                read_json=lambda p:json.loads(p.read_text()))
        health=function(SOURCE/'fc27_cloud_api.py','health',ns)
        for status,count in (('COMPLETED',0),('UNKNOWN',1)):
            body=dict(operation_id=self.execution,status=status,order_close={'reason':'order_write_confirmed_admin_price_matched'})
            self.db.execute('INSERT OR REPLACE INTO operations VALUES(?,?)',(self.execution,json.dumps(body)));self.db.commit()
            with patch('urllib.request.urlopen',side_effect=OSError('isolated_no_network')):
                self.assertEqual(health()['incomplete_executions'],count)
        path.write_text(json.dumps(self.audit(status='PUBLIC_CONFIRMED',execution_id='other')))
        with patch('urllib.request.urlopen',side_effect=OSError('isolated_no_network')):
            self.assertEqual(health()['incomplete_executions'],1)


class PausedCodePublish(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for name in ('v3','queue','jobs','executions','all-coin-sync','player-sync','state'):(self.root/name).mkdir()
        self.db=sqlite3.connect(self.root/'v3/control.sqlite3');self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE operations(id TEXT PRIMARY KEY,body TEXT); CREATE TABLE metadata(id TEXT PRIMARY KEY,body TEXT); CREATE TABLE pricing_plans(id TEXT PRIMARY KEY,body TEXT); CREATE TABLE plan_ownership(resource TEXT PRIMARY KEY,plan_id TEXT,revision INTEGER,generation TEXT);')
        self.db.execute('INSERT INTO metadata VALUES(?,?)',('generation',json.dumps({'id':'current'})))
        self.plan('one','SUSPENDED')
        self.ns=dict(ROOT=self.root,read_record=lambda p:json.loads(p.read_text()),
                     resolved_execution=function(SOURCE/'automation_tick.py','resolved_execution',dict(ROOT=self.root)),
                     player_sync_gate=lambda:'needs_reconcile')
        self.guard=function(SOURCE/'automation_tick.py','retry_guard',self.ns)
        self.tick=SimpleNamespace(ROOT=self.root,retry_guard=self.guard,read_record=self.ns['read_record'],
            resolved_execution=self.ns['resolved_execution'],load_player_sync_policy=lambda:{'revision':10},
            RETRY_LOCKS=('price-writer.lock','restore.lock'),queue_mutation=self.queue_mutation)
        for name in self.tick.RETRY_LOCKS:(self.root/'state'/name).touch()
        self.health={'incomplete_executions':0,'queue_depth':0};self.api=SimpleNamespace(health=lambda:self.health)
        scope={'json':json,'superseded_all_code_release':lambda *a,**k:False}
        self.paused=function(SOURCE.parent/'deploy/release_readiness.py','paused_code_release',scope)
        self.ready=function(SOURCE.parent/'deploy/release_readiness.py','fc_release_quiescent',scope)
        self.all_path=self.root/'all-coin-sync/pending.json';self.all_path.write_text(json.dumps({'status':'needs_reconcile','steps':[{'platform':'PC','status':'pending'}]}))
        self.old_all=self.all_path.read_bytes()
    def plan(self,ident,state,revision=3,generation='current'):
        plan=dict(plan_id=ident,state=state,revision=revision,generation=generation)
        self.db.execute('INSERT OR REPLACE INTO pricing_plans VALUES(?,?)',(ident,json.dumps(plan)))
        self.db.execute('INSERT OR REPLACE INTO plan_ownership VALUES(?,?,?,?)',(ident,ident,revision,generation));self.db.commit()
    @contextmanager
    def queue_mutation(self):
        yield
    def test_paused_publication_preserves_all_and_player_business_gates(self):
        self.assertEqual(self.guard(),'all_sync_unconfirmed')
        self.assertTrue(self.ready(self.tick,self.api,locks_held=True))
        self.assertEqual(self.all_path.read_bytes(),self.old_all)
        self.assertEqual(self.guard(),'all_sync_unconfirmed')
        self.all_path.unlink()
        self.assertEqual(self.guard(),'player_sync_unconfirmed')
        self.assertTrue(self.ready(self.tick,self.api,locks_held=True))
        self.assertEqual(self.guard(),'player_sync_unconfirmed')
    def test_every_current_owner_must_be_suspended_and_match_revision(self):
        self.plan('two','ACTIVE')
        self.assertFalse(self.ready(self.tick,self.api,locks_held=True))
        self.plan('two','SUSPENDED')
        self.assertTrue(self.ready(self.tick,self.api,locks_held=True))
        self.db.execute("UPDATE plan_ownership SET revision=99 WHERE plan_id='two'");self.db.commit()
        self.assertFalse(self.ready(self.tick,self.api,locks_held=True))
    def test_old_generation_does_not_replace_current_ownership_proof(self):
        self.plan('old','ACTIVE',generation='retired')
        self.assertTrue(self.ready(self.tick,self.api,locks_held=True))
        self.db.execute("DELETE FROM plan_ownership WHERE generation='current'");self.db.commit()
        self.assertFalse(self.ready(self.tick,self.api,locks_held=True))
    def test_queue_running_and_unknown_price_still_block_code_publication(self):
        for folder,body in (('queue',{'status':'queued'}),('jobs',{'status':'running'}),('executions',{'status':'UNCERTAIN'})):
            with self.subTest(folder=folder):
                path=self.root/folder/'active.json';path.write_text(json.dumps(body))
                self.assertFalse(self.ready(self.tick,self.api,locks_held=True));path.unlink()
        self.health['incomplete_executions']=1
        self.assertFalse(self.ready(self.tick,self.api,locks_held=True))
    def test_missing_generation_or_malformed_ledger_is_not_paused_proof(self):
        self.db.execute("UPDATE metadata SET body='{}'");self.db.commit()
        self.assertFalse(self.ready(self.tick,self.api,locks_held=True))
    @unittest.skipUnless(os.name=='posix','requires real Linux flock')
    def test_real_retry_lock_contention_blocks_and_unlock_allows_same_readonly_check(self):
        import fcntl
        path=self.root/'state'/self.tick.RETRY_LOCKS[0]
        with path.open('rb') as held:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertFalse(self.ready(self.tick,self.api))
        self.assertTrue(self.ready(self.tick,self.api))
        self.assertEqual(self.guard(),'all_sync_unconfirmed')
    @unittest.skipUnless(os.name=='posix','requires actual adapter Linux lock scope')
    def test_adapter_only_passes_held_flag_inside_actual_combined_locks(self):
        from unittest.mock import Mock
        import fcntl
        text=(SOURCE.parent/'deploy/fc_v3_release_adapter.py').read_text('utf-8');tree=ast.parse(text)
        load=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='load_base')
        selected=[n for n in load.body if (isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id in ('holding_fc_locks','bundle_release_state')) or isinstance(n,ast.FunctionDef) and n.name in ('combined_locks','guards')]
        selected.append(ast.parse('return combined_locks,guards').body[0])
        factory=ast.FunctionDef(name='factory',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),body=selected,decorator_list=[])
        module=ast.fix_missing_locations(ast.Module(body=[factory],type_ignores=[]))
        ready=Mock(return_value=True)
        fc=SimpleNamespace(ROOT=self.root,tick=self.tick,api=SimpleNamespace(queue_mutation=self.queue_mutation))
        def no_target_link(path):
            path.relative_to(self.root)
            if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('fixture_target_link')
        base=SimpleNamespace(no_target_link=no_target_link,rooted=lambda _root,path:self.root/path.lstrip('/'))
        scope=dict(contextmanager=contextmanager,ExitStack=ExitStack,Path=Path,fc=fc,original_locks=lambda _:self.queue_mutation(),
                   original_guards=lambda *a:None,fc_release_quiescent=ready,base=base,
                   scope='legacy-fixture',THREE_PLATFORM_SCOPE='three-platform')
        exec(compile(module,'original-adapter-lock-scope','exec'),scope)
        locks,guards=scope['factory']()
        manifest={'files':[]};guards(manifest,Path('/'))
        self.assertFalse(ready.call_args.kwargs['locks_held'])
        with locks(Path('/')):
            guards(manifest,Path('/'));self.assertTrue(ready.call_args.kwargs['locks_held'])
            with (self.root/'state'/self.tick.RETRY_LOCKS[0]).open('rb') as other:
                with self.assertRaises(BlockingIOError):fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
        guards(manifest,Path('/'));self.assertFalse(ready.call_args.kwargs['locks_held'])

class SupersededAllCodePublish(unittest.TestCase):
    def test_code_publisher_restarts_the_scheduler_that_imports_runtime_and_engine(self):
        from unittest.mock import Mock
        sys.path.insert(0,str(SOURCE.parent/'deploy'))
        from target_map import CURVE_AVERAGE_SCOPE, CURVE_V6_SCOPE, CURVE_INSURANCE_SCOPE, CURVE_STABILITY_SCOPE, CURVE_MARKET_SCOPE, CURVE_WEEKLY_SCOPE, CURVE_REVIEW_SCOPE, CURVE_MARGIN_BAND_SCOPE, LOOTBAR_CALLER_SCOPE
        from target_map import CURVE_ARAB_QUOTE_SCOPE, CURVE_RECOVERY_SCOPES
        path=SOURCE.parent/'deploy/fc_v3_release_adapter.py'
        load=next(n for n in ast.parse(path.read_text('utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='load_base')
        restart=next(n for n in load.body if isinstance(n,ast.FunctionDef) and n.name=='restart')
        process=SimpleNamespace(run=Mock())
        scope=dict(subprocess=process,base=SimpleNamespace(HERMES_UPDATE_SCOPE='reader-update'),HISTORY_READ_SCOPE='history-read',original_restart=Mock(),restart_with_hermes_readiness=Mock(),LOOTBAR_CALLER_SCOPE=LOOTBAR_CALLER_SCOPE,
                   SCOPE='full',DELTA_SCOPE='delta',SHADOW_SCOPE='shadow',OPERATING_SCOPE='operating',COLLECTION_SCOPE='collection',BIDIRECTIONAL_SCOPE='bidirectional',REPAIR_SCOPE='repair',QUOTE_FRAGMENT_SCOPE='quote-fragment',QUOTE_PREVIEW_SCOPE='quote-preview',DAILY_REPAIR_SCOPE='daily-repair',DAILY_SUMMARY_SCOPE='daily-summary',COUPON_DISPLAY_SCOPE='coupon-display',THREE_PLATFORM_SCOPE='three-platform',bundle_readiness=Mock())
        exec(compile(ast.Module(body=[restart],type_ignores=[]),str(path),'exec'),scope)
        scope['CURVE_V6_SCOPE'] = CURVE_V6_SCOPE
        scope['CURVE_AVERAGE_SCOPE'] = CURVE_AVERAGE_SCOPE
        scope['CURVE_INSURANCE_SCOPE'] = CURVE_INSURANCE_SCOPE
        scope['CURVE_STABILITY_SCOPE'] = CURVE_STABILITY_SCOPE
        scope['CURVE_MARKET_SCOPE'] = CURVE_MARKET_SCOPE
        scope['CURVE_WEEKLY_SCOPE'] = CURVE_WEEKLY_SCOPE
        scope['CURVE_REVIEW_SCOPE'] = CURVE_REVIEW_SCOPE
        scope['CURVE_MARGIN_BAND_SCOPE'] = CURVE_MARGIN_BAND_SCOPE
        scope['CURVE_ARAB_QUOTE_SCOPE'] = CURVE_ARAB_QUOTE_SCOPE
        scope['CURVE_RECOVERY_SCOPES'] = CURVE_RECOVERY_SCOPES
        for kind in ('full','delta','shadow','operating','bidirectional','repair','quote-fragment','quote-preview','daily-repair','daily-summary','coupon-display','three-platform',CURVE_V6_SCOPE):
            process.run.reset_mock();scope['restart_with_hermes_readiness'].reset_mock();scope['restart']({'scope':kind})
            restarts=[c.args[0] for c in process.run.call_args_list if c.args[0][:2]==['systemctl','restart']]
            expected=('fc27-cloud-api.service','fc27-cloud-worker.service','fc-pricing-v3.service')
            if kind=='three-platform':expected+=('fc27-pack-bundles.service',)
            self.assertEqual(restarts,[['systemctl','restart',name] for name in expected])
            scope['restart_with_hermes_readiness'].assert_called_once()
        for kind in (CURVE_AVERAGE_SCOPE, CURVE_MARGIN_BAND_SCOPE, *CURVE_RECOVERY_SCOPES.values()):
            with self.subTest(scope=kind):
                process.run.reset_mock()
                scope['restart_with_hermes_readiness'].reset_mock()
                scope['restart']({'scope':kind}, 'fence')
                restarts=[c.args[0] for c in process.run.call_args_list if c.args[0][:2]==['systemctl','restart']]
                self.assertEqual(restarts,[['systemctl','restart',name] for name in (
                    'fc27-cloud-api.service','fc27-cloud-worker.service','fc-pricing-v3.service')])
                if kind == CURVE_RECOVERY_SCOPES['market-packages']:
                    scope['restart_with_hermes_readiness'].assert_called_once_with(
                        scope['base'], scope['original_restart'], {'scope':kind}, 'fence')
                else:
                    scope['restart_with_hermes_readiness'].assert_not_called()
        process.run.reset_mock();scope['restart_with_hermes_readiness'].reset_mock()
        scope['restart']({'scope':'history-read'}, 'fence')
        process.run.assert_not_called()
        call=scope['restart_with_hermes_readiness'].call_args
        self.assertEqual(call.args[2], {'scope':'reader-update'})
        self.assertEqual(call.args[3], 'fence')

    def setUp(self):
        from test_reconcile_original import all_step
        sys.path.insert(0,str(SOURCE.parent/'deploy'))
        import release_readiness
        self.release=release_readiness
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for name in ('queue','jobs','executions','all-coin-sync','state'):(self.root/name).mkdir()
        self.old=dict(execution_id='original',status='needs_reconcile',steps=[all_step('PC','pending')])
        self.latest=dict(execution_id='later',status='confirmed',completed_at='2026-10-30T02:48:58+00:00',
            source_confirmation={'status':'confirmed'},steps=[all_step(p,'confirmed') for p in ('PS','XBOX','PC')])
        self.old_audit=dict(execution_id='original',status='PUBLIC_CONFIRMED',sync_confirmed=True,updated_at='2026-10-29T15:21:28+00:00')
        self.later_audit=dict(execution_id='later',status='CONFIRMED',sync_confirmed=True,all_baseline={'status':'confirmed'})
        self.persist()
        self.tick=SimpleNamespace(ROOT=self.root,read_record=lambda p:json.loads(p.read_text()),
            resolved_execution=lambda a:a.get('status') in ('CONFIRMED','PUBLIC_CONFIRMED'),
            RETRY_LOCKS=('price-writer.lock',),queue_mutation=self.queue_mutation,
            retry_guard=lambda:'all_sync_unconfirmed',player_sync_gate=lambda:'ready',load_player_sync_policy=lambda:{'revision':10})
        (self.root/'state/price-writer.lock').touch()
        self.health={'incomplete_executions':0,'queue_depth':0};self.api=SimpleNamespace(health=lambda:self.health)
    def persist(self):
        for folder,ident,body in [('all-coin-sync','original',self.old),('all-coin-sync','later',self.latest),
                                  ('executions','original',self.old_audit),('executions','later',self.later_audit)]:
            (self.root/folder/(ident+'.json')).write_text(json.dumps(body))
    @contextmanager
    def queue_mutation(self):yield
    def check(self,mutate=None,held=True):
        import coin_all_sync_job as coins
        steps={s['platform']:s for s in self.latest['steps']}
        def read(manager,platform,site):
            from copy import deepcopy
            row=deepcopy(steps[platform]['source' if site==266 else 'payload'])
            return mutate(row,platform,site) if mutate else row
        admin=SimpleNamespace(read_private_config=lambda:{},SessionManager=lambda _:SimpleNamespace(ensure=lambda:True))
        with patch.dict(sys.modules,{'fc_shared_admin':admin}),patch.object(coins,'read_row',side_effect=read),\
                patch.object(coins,'api',side_effect=AssertionError('no_price_POST')),patch.object(self.release.time,'sleep'):
            return self.release.superseded_all_code_release(self.tick,self.health,locks_held=held)
    def test_full_later_confirmation_and_two_fresh_rounds_preserve_original_bytes(self):
        before={str(p):p.read_bytes() for folder in ('all-coin-sync','executions') for p in (self.root/folder).glob('*.json')}
        self.assertTrue(self.check())
        self.assertEqual(before,{str(p):p.read_bytes() for folder in ('all-coin-sync','executions') for p in (self.root/folder).glob('*.json')})
        self.assertEqual(self.tick.retry_guard(),'all_sync_unconfirmed')
    def test_same_id_order_admin_close_allows_code_release_without_all_replay(self):
        (self.root/'all-coin-sync/later.json').unlink()
        (self.root/'executions/later.json').unlink()
        (self.root/'v3').mkdir()
        operation=dict(operation_id='original',status='COMPLETED',
            order_close={'reason':'order_write_confirmed_admin_price_matched'})
        with closing(sqlite3.connect(str(self.root/'v3/control.sqlite3'))) as db,db:
            db.execute('CREATE TABLE operations(id TEXT PRIMARY KEY,body TEXT NOT NULL)')
            db.execute('INSERT INTO operations VALUES (?,?)',('original',json.dumps(operation)))
        before=(self.root/'all-coin-sync/original.json').read_bytes()
        self.assertTrue(self.check())
        self.assertEqual((self.root/'all-coin-sync/original.json').read_bytes(),before)
        self.assertEqual(self.tick.retry_guard(),'all_sync_unconfirmed')
        for field,value in [('status','UNKNOWN'),('operation_id','another'),('order_close',{})]:
            changed=dict(operation,**{field:value})
            with closing(sqlite3.connect(str(self.root/'v3/control.sqlite3'))) as db,db:
                db.execute('UPDATE operations SET body=?',(json.dumps(changed),))
            self.assertFalse(self.check())
    def test_dispatch_unknown_or_unclosed_original_still_blocks(self):
        for state in ('dispatching','unknown'):
            self.old['steps'][0]['status']=state;self.persist();self.assertFalse(self.check())
        self.old['steps'][0]['status']='pending';self.old_audit['status']='UNCERTAIN';self.persist();self.assertFalse(self.check())
    def test_later_partial_stale_or_wrong_product_is_not_supersession(self):
        from copy import deepcopy
        good=deepcopy(self.latest)
        for field,value in [('status','needs_reconcile'),('completed_at','2026-10-28T00:00:00+00:00'),('completed_at','2999-01-01T00:00:00+00:00')]:
            self.latest=deepcopy(good);self.latest[field]=value;self.persist();self.assertFalse(self.check())
        self.latest=deepcopy(good);self.latest['steps'][0]['product_id']=123;self.persist();self.assertFalse(self.check())
    def test_current_price_tier_or_source_change_blocks_without_writes(self):
        def mismatch(row,p,site):
            if p=='PC' and site==0:row['more']['price']=['different']
            return row
        self.assertFalse(self.check(mismatch))
        def source_changed(row,p,site):
            if p=='PS' and site==266:row['unit_price']='99'
            return row
        self.assertFalse(self.check(source_changed))
        calls=[]
        def unstable(row,p,site):
            calls.append(p)
            if len(calls)>6:row['keywords']='changed'
            return row
        self.assertFalse(self.check(unstable))
    def test_running_queue_unknown_and_player_guard_are_preserved(self):
        for folder,body in [('queue',{}),('jobs',{'status':'running'}),('executions',{'status':'UNCERTAIN'})]:
            path=self.root/folder/'active.json';path.write_text(json.dumps(body))
            self.assertFalse(self.check());path.unlink()
        self.health['incomplete_executions']=1;self.assertFalse(self.check());self.health['incomplete_executions']=0
        with patch.object(self.release,'superseded_all_code_release',return_value=True):
            self.assertTrue(self.release.fc_release_quiescent(self.tick,self.api,locks_held=True))
            self.tick.player_sync_gate=lambda:'needs_reconcile'
            self.assertFalse(self.release.fc_release_quiescent(self.tick,self.api,locks_held=True))
    def test_superseded_all_keeps_existing_proven_player_prewrite_refusal_contract(self):
        self.tick.player_sync_gate=lambda:'needs_reconcile'
        self.tick.load_player_sync_policy=lambda:{'revision':10}
        path=self.root/'jobs/player.json'
        job=dict(job_id='player',kind='player_sync',created_at='2026-10-30T04:03:52+00:00',
                 request={'config_revision':10},status='failed',error='player_sync_not_confirmed',
                 sync_result={'status':'blocked_before_write','reason':'player_sync_preflight_changed'})
        path.write_text(json.dumps(job))
        with patch.object(self.release,'superseded_all_code_release',return_value=True):
            self.assertTrue(self.release.fc_release_quiescent(self.tick,self.api,locks_held=True))
            job['sync_result']={'status':'unknown'};path.write_text(json.dumps(job))
            self.assertFalse(self.release.fc_release_quiescent(self.tick,self.api,locks_held=True))
    @unittest.skipUnless(os.name=='posix','requires real Linux flock')
    def test_original_retry_lock_contention_blocks_same_read_only_proof(self):
        import fcntl
        with (self.root/'state/price-writer.lock').open('rb') as held:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB);self.assertFalse(self.check(held=False))
        self.assertTrue(self.check(held=False))

if __name__=='__main__':unittest.main()
